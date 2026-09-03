import os
from datetime import datetime, timedelta
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, jsonify, render_template, request
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "seo_bot_db"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
}


def db():
    return psycopg2.connect(**DB_CONFIG)


def query(sql, params=()):
    with db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


@app.get("/")
def index():
    return render_template("index.html")

def automation_filter(mode):
    mode = (mode or "YOUTUBE").upper()

    if mode not in {"YOUTUBE", "SEARCH"}:
        mode = "YOUTUBE"

    return mode


@app.get("/api/dashboard")
def dashboard():

    try:
        days = max(
            1,
            min(
                int(request.args.get("days", 7)),
                90
            )
        )

        automation_type = automation_filter(
            request.args.get(
                "automation",
                "YOUTUBE"
            )
        )

        print(
            f"[DASHBOARD API] "
            f"automation={automation_type}, "
            f"days={days}"
        )

        # -------------------------------------------------
        # SUMMARY
        # -------------------------------------------------

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
                NOW() - (%s * INTERVAL '1 day')

              AND UPPER(
                    TRIM(automation_type)
                  ) = %s
            """,
            (
                days,
                automation_type
            )
        )[0]

        total = summary["total_runs"] or 0

        summary["success_rate"] = (
            round(
                (
                    summary["successful_runs"]
                    / total
                ) * 100,
                1
            )
            if total
            else 0
        )

        # -------------------------------------------------
        # DAILY
        # -------------------------------------------------

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
                NOW() - (%s * INTERVAL '1 day')

              AND UPPER(
                    TRIM(automation_type)
                  ) = %s

            GROUP BY DATE(started_at)

            ORDER BY day
            """,
            (
                days,
                automation_type
            )
        )

        # -------------------------------------------------
        # ENGINES
        # -------------------------------------------------

        engines = query("""
            SELECT
                COALESCE(search_engine, 'Unknown') AS engine,
                COUNT(*)::int AS total,
                COUNT(*) FILTER (WHERE status = 'SUCCESS')::int AS success,
                COUNT(*) FILTER (WHERE status = 'FAILED')::int AS failed
            FROM automation_runs
            WHERE started_at >= NOW() - (%s * INTERVAL '1 day')
            AND UPPER(TRIM(automation_type)) = %s
            AND search_engine IS NOT NULL
            GROUP BY COALESCE(search_engine, 'Unknown')
            ORDER BY total DESC
        """, (days, automation_type))

        # -------------------------------------------------
        # RECENT RUNS
        # -------------------------------------------------

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

            WHERE UPPER(
                    TRIM(automation_type)
                  ) = %s

            ORDER BY started_at DESC

            LIMIT 50
            """,
            (
                automation_type,
            )
        )

        # -------------------------------------------------
        # RESPONSE
        # -------------------------------------------------

        response = {
            "automation": automation_type,

            "summary": summary,

            "daily": daily,

            "engines": engines,

            "recent": recent,

            "generated_at":
                datetime.now().isoformat()
        }

        print(
            "[DASHBOARD API RESULT]",
            automation_type,
            "total_runs =",
            summary["total_runs"]
        )

        return jsonify(response)

    except Exception as error:

        print(
            "[DASHBOARD API ERROR]",
            repr(error)
        )

        return jsonify(
            {
                "error": str(error)
            }
        ), 500


@app.get("/api/logs/<run_id>")
def logs(run_id):
    rows = query("""
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
        ORDER BY timestamp ASC, log_id ASC
    """, (run_id,))

    return jsonify(rows)


@app.get("/api/health")
def health():
    try:
        query("SELECT 1 AS ok")
        return jsonify({"status": "connected"})
    except Exception as exc:
        return jsonify({"status": "disconnected", "error": str(exc)}), 503


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=True)
