import os
import time
from datetime import datetime
from threading import Lock

import psycopg2
from psycopg2 import OperationalError
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor
from flask import Flask, jsonify, render_template, request
from dotenv import load_dotenv


# =========================================================
# ENVIRONMENT
# =========================================================

load_dotenv()

app = Flask(__name__)


# =========================================================
# DATABASE CONFIGURATION
# =========================================================

DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "seo_bot_db"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
}

# Keep local configuration unchanged unless DB_SSLMODE
# is explicitly provided in the environment.
if os.getenv("DB_SSLMODE"):
    DB_CONFIG["sslmode"] = os.getenv("DB_SSLMODE")


# =========================================================
# DATABASE CONNECTION POOL
# =========================================================
#
# The old version opened a new PostgreSQL connection for
# every query. With Aiven/remote PostgreSQL, that means
# repeated TCP/SSL connection overhead.
#
# The dashboard now keeps a small reusable connection pool.
# =========================================================

POOL_MIN = max(
    1,
    int(os.getenv("DASHBOARD_DB_POOL_MIN", "1"))
)

POOL_MAX = max(
    POOL_MIN,
    int(os.getenv("DASHBOARD_DB_POOL_MAX", "5"))
)

_pool_lock = Lock()
_db_pool = None


def create_db_pool():
    return ThreadedConnectionPool(
        minconn=POOL_MIN,
        maxconn=POOL_MAX,
        **DB_CONFIG,
    )


def get_db_pool():
    global _db_pool

    if _db_pool is None:
        with _pool_lock:
            if _db_pool is None:
                _db_pool = create_db_pool()

    return _db_pool


def reset_db_pool():
    """
    Recreate the pool after a PostgreSQL connection-level
    failure. This is only used for OperationalError.
    """
    global _db_pool

    with _pool_lock:
        old_pool = _db_pool
        _db_pool = None

        if old_pool is not None:
            try:
                old_pool.closeall()
            except Exception:
                pass

        _db_pool = create_db_pool()

    return _db_pool


# =========================================================
# DATABASE QUERY
# =========================================================

def query(sql, params=(), retries=1):
    """
    Execute a read query through the reusable connection pool.

    On a connection-level OperationalError:
      1. discard the bad connection
      2. recreate the pool
      3. retry once

    Normal SQL errors are NOT swallowed or retried.
    """

    last_error = None

    for attempt in range(retries + 1):
        conn = None
        query_start = time.perf_counter()

        try:
            pool = get_db_pool()
            conn = pool.getconn()

            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute(sql, params)

                rows = [
                    dict(row)
                    for row in cur.fetchall()
                ]

            elapsed_ms = (
                time.perf_counter()
                - query_start
            ) * 1000

            print(
                "[DASHBOARD DB]",
                f"time={elapsed_ms:.1f}ms",
                f"rows={len(rows)}",
            )

            return rows

        except OperationalError as error:
            last_error = error

            print(
                "[DASHBOARD DB]",
                f"connection error "
                f"attempt={attempt + 1}/{retries + 1}:",
                repr(error),
            )

            # Do not return a known-bad connection to the pool.
            if conn is not None:
                try:
                    pool.putconn(
                        conn,
                        close=True
                    )
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass

                conn = None

            if attempt < retries:
                try:
                    reset_db_pool()
                except Exception as reset_error:
                    print(
                        "[DASHBOARD DB] "
                        "pool reset failed:",
                        repr(reset_error),
                    )

                continue

            raise last_error

        finally:
            if conn is not None:
                try:
                    get_db_pool().putconn(conn)
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass


# =========================================================
# BASIC ROUTES
# =========================================================

@app.get("/")
def index():
    return render_template("index.html")


def automation_filter(mode):
    mode = (mode or "YOUTUBE").upper()

    if mode not in {"YOUTUBE", "SEARCH"}:
        mode = "YOUTUBE"

    return mode


# =========================================================
# DASHBOARD API
# =========================================================

@app.get("/api/dashboard")
def dashboard():

    request_start = time.perf_counter()

    try:
        days = max(
            1,
            min(
                int(request.args.get("days", 7)),
                90,
            ),
        )

        if days == 1:
            period_start = "CURRENT_DATE"
        else:
            period_start = f"CURRENT_DATE - INTERVAL '{days - 1} days'"

        automation_type = automation_filter(
            request.args.get(
                "automation",
                "YOUTUBE",
            )
        )

        print(
            "[DASHBOARD API]",
            f"automation={automation_type}",
            f"days={days}",
        )

        # -------------------------------------------------
        # SUMMARY
        # -------------------------------------------------

        query_start = time.perf_counter()

        summary = query(
            """
            SELECT
                COUNT(*)::int AS total_runs,

                COUNT(*) FILTER (
                    WHERE status = 'SUCCESS'
                )::int AS successful_runs,

                COUNT(*) FILTER (
                    WHERE status = 'FAILED'
                )::int AS failed_runs,

                COUNT(*) FILTER (
                    WHERE status = 'RUNNING'
                )::int AS running_runs,

                COUNT(*) FILTER (
                    WHERE status = 'INTERRUPTED'
                )::int AS interrupted_runs,

                COALESCE(
                    SUM(retry_count),
                    0
                )::int AS total_retries,

                COUNT(
                    DISTINCT original_keyword
                )::int AS unique_keywords

            FROM automation_runs

            WHERE started_at >=
                CURRENT_DATE - ((%s - 1) * INTERVAL '1 day')

              AND UPPER(
                    TRIM(automation_type)
                  ) = %s
            """,
            (
                days,
                automation_type,
            ),
        )[0]

        print(
            "[DASHBOARD API]",
            f"summary="
            f"{(time.perf_counter() - query_start) * 1000:.1f}ms",
        )

        total = summary["total_runs"] or 0

        summary["success_rate"] = (
            round(
                (
                    summary["successful_runs"]
                    / total
                ) * 100,
                1,
            )
            if total
            else 0
        )

        # -------------------------------------------------
        # DAILY
        # -------------------------------------------------

        query_start = time.perf_counter()

        daily = query(
            """
            SELECT
                DATE(started_at) AS day,

                COUNT(*)::int AS total,

                COUNT(*) FILTER (
                    WHERE status = 'SUCCESS'
                )::int AS success,

                COUNT(*) FILTER (
                    WHERE status = 'FAILED'
                )::int AS failed

            FROM automation_runs

            WHERE started_at >=
                CURRENT_DATE - ((%s - 1) * INTERVAL '1 day')

              AND UPPER(
                    TRIM(automation_type)
                  ) = %s

            GROUP BY DATE(started_at)

            ORDER BY day
            """,
            (
                days,
                automation_type,
            ),
        )

        print(
            "[DASHBOARD API]",
            f"daily="
            f"{(time.perf_counter() - query_start) * 1000:.1f}ms",
        )

        # -------------------------------------------------
        # ENGINES
        # -------------------------------------------------

        query_start = time.perf_counter()

        engines = query(
            """
            SELECT
                COALESCE(
                    search_engine,
                    'Unknown'
                ) AS engine,

                COUNT(*)::int AS total,

                COUNT(*) FILTER (
                    WHERE status = 'SUCCESS'
                )::int AS success,

                COUNT(*) FILTER (
                    WHERE status = 'FAILED'
                )::int AS failed

            FROM automation_runs

            WHERE started_at >=
                CURRENT_DATE - ((%s - 1) * INTERVAL '1 day')

              AND UPPER(
                    TRIM(automation_type)
                  ) = %s

              AND search_engine IS NOT NULL

              AND LOWER(
                    TRIM(search_engine)
                  ) <> 'youtube'

            GROUP BY COALESCE(
                search_engine,
                'Unknown'
            )

            ORDER BY total DESC
            """,
            (
                days,
                automation_type,
            ),
        )

        print(
            "[DASHBOARD API]",
            f"engines="
            f"{(time.perf_counter() - query_start) * 1000:.1f}ms",
        )

        # -------------------------------------------------
        # RECENT RUNS
        # -------------------------------------------------

        query_start = time.perf_counter()

        recent = query(
            """
            SELECT
                run_id,
                automation_type,
                original_keyword,
                search_keyword,
                browser_mode,
                target,
                search_engine,
                started_at,
                finished_at,
                status,
                success_count,
                failure_count,
                retry_count,
                fallback_used,

                ROUND(
                    EXTRACT(
                        EPOCH FROM
                        (
                            COALESCE(
                                finished_at,
                                NOW()
                            )
                            - started_at
                        )
                    )::numeric,
                    1
                ) AS duration_seconds

            FROM automation_runs
            WHERE started_at >= CURRENT_DATE - ((%s - 1) * INTERVAL '1 day')
            AND UPPER(TRIM(automation_type)) = %s
            ORDER BY started_at DESC
            LIMIT 50
            """,
            (
                 days,
                automation_type,
            ),
        )

        print(
            "[DASHBOARD API]",
            f"recent="
            f"{(time.perf_counter() - query_start) * 1000:.1f}ms",
        )

        # -------------------------------------------------
        # YOUTUBE PERFORMANCE
        # -------------------------------------------------
        # YouTube Performance represents the selected YouTube
        # automation itself, not a search-engine row.
        youtube = None

        if automation_type == "YOUTUBE":
            youtube = {
                "total": int(summary.get("total_runs") or 0),
                "success": int(summary.get("successful_runs") or 0),
                "failed": int(summary.get("failed_runs") or 0),
                "success_rate": float(summary.get("success_rate") or 0),
            }

        response = {
            "automation": automation_type,
            "summary": summary,
            "daily": daily,
            "engines": engines,
            "youtube": youtube,
            "recent": recent,
            "generated_at":
                datetime.now().isoformat(),
        }

        total_ms = (
            time.perf_counter()
            - request_start
        ) * 1000

        print(
            "[DASHBOARD API RESULT]",
            automation_type,
            "total_runs =",
            summary["total_runs"],
            f"total_time={total_ms:.1f}ms",
        )

        return jsonify(response)

    except Exception as error:

        total_ms = (
            time.perf_counter()
            - request_start
        ) * 1000

        print(
            "[DASHBOARD API ERROR]",
            repr(error),
            f"after={total_ms:.1f}ms",
        )

        return jsonify(
            {
                "error": str(error)
            }
        ), 500


# =========================================================
# LIVE LOGS
# =========================================================

@app.get("/api/logs/<run_id>")
def logs(run_id):

    request_start = time.perf_counter()

    try:
        rows = query(
            """
            SELECT
                log_id,
                timestamp,
                level,
                keyword,
                search_engine,
                action,
                event_status,
                url,
                error_message,
                metadata,
                message

            FROM automation_logs

            WHERE run_id = %s

            ORDER BY
                timestamp ASC,
                log_id ASC
            """,
            (run_id,),
        )

        print(
            "[DASHBOARD LOGS]",
            f"run_id={run_id}",
            f"rows={len(rows)}",
            f"time="
            f"{(time.perf_counter() - request_start) * 1000:.1f}ms",
        )

        return jsonify(rows)

    except Exception as error:

        print(
            "[DASHBOARD LOGS ERROR]",
            repr(error),
        )

        return jsonify(
            {
                "error": str(error)
            }
        ), 500


# =========================================================
# HEALTH
# =========================================================

@app.get("/api/health")
def health():

    try:
        result = query(
            """
            SELECT
                current_database() AS database_name,
                current_user AS database_user,
                inet_server_addr()::text AS server_address,
                inet_server_port() AS server_port,
                NOW() AS database_time
            """
        )[0]

        return jsonify(
            {
                "status": "connected",
                "database": result["database_name"],
                "user": result["database_user"],
                "server": result["server_address"],
                "port": result["server_port"],
                "database_time":
                    result["database_time"],
            }
        )

    except Exception as exc:

        print(
            "[DASHBOARD HEALTH ERROR]",
            repr(exc),
        )

        return jsonify(
            {
                "status": "disconnected",
                "error": str(exc),
            }
        ), 503


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":

    # debug=False intentionally avoids Flask's development
    # reloader while we diagnose dashboard stability.
    app.run(
        host="127.0.0.1",
        port=5050,
        debug=False,
        threaded=True,
    )
