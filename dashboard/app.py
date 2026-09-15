import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from threading import Lock

from pymongo import MongoClient, DESCENDING, ASCENDING
from flask import Flask, jsonify, render_template, request
from dotenv import load_dotenv


# =========================================================
# ENVIRONMENT + DB SELECTION (config.json -> .env)
# =========================================================
#
# config.json:
#   "database": {
#     "current_db": "atlas",
#     "db": { "local": "MONGO_URI_LOCAL", "atlas": "MONGO_URI_ATLAS" }
#   }
# .env:
#   MONGO_URI_LOCAL=mongodb://localhost:27017/seo_bot_db
#   MONGO_URI_ATLAS=mongodb+srv://<user>:<pass>@<cluster>/seo_bot_db?retryWrites=true&w=majority
#
# Switch DB by changing database.current_db in config.json.

load_dotenv()

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]

with open(BASE_DIR / "config.json", encoding="utf-8") as file:
    _CONFIG = json.load(file)

_DB_CONFIG = _CONFIG.get("database", {})
CURRENT_DB = _DB_CONFIG.get("current_db", "atlas")
_DB_ENV_VAR = _DB_CONFIG.get("db", {}).get(CURRENT_DB)

if not _DB_ENV_VAR:
    raise ValueError(
        f"Dashboard database is not configured for '{CURRENT_DB}'. "
        "Set database.current_db and database.db in config.json."
    )

MONGO_URI = os.getenv(_DB_ENV_VAR)

if not MONGO_URI:
    raise ValueError(
        f"Environment variable '{_DB_ENV_VAR}' is not set. "
        "Set it in .env (MONGO_URI_LOCAL / MONGO_URI_ATLAS)."
    )

MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "").strip() or None

print(f"[DASHBOARD DB] environment={CURRENT_DB} (env: {_DB_ENV_VAR})")


# =========================================================
# MONGO CLIENT (lazy singleton)
# =========================================================

_client_lock = Lock()
_client = None
_db = None


def _resolve_db_name(client):
    if MONGO_DB_NAME:
        return MONGO_DB_NAME
    try:
        default_db = client.get_default_database()
        if default_db is not None:
            return default_db.name
    except Exception:
        pass
    try:
        path = MONGO_URI.split("?", 1)[0].rsplit("/", 1)[-1]
        if path and not path.startswith("mongodb"):
            return path
    except Exception:
        pass
    return os.getenv("MONGO_DB_FALLBACK", "seo_bot_db")


def get_mongo_db():
    global _client, _db
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = MongoClient(
                    MONGO_URI,
                    serverSelectionTimeoutMS=int(
                        os.getenv("MONGO_SERVER_SELECTION_TIMEOUT_MS", "5000")
                    ),
                )
                _db = _client[_resolve_db_name(_client)]
    return _db


def runs_collection():
    return get_mongo_db()["automation_runs"]


def logs_collection():
    return get_mongo_db()["automation_logs"]


def backlinks_collection():
    """Dedicated per-submission backlink results (one doc per ping-site x URL)."""
    return get_mongo_db()["backlinks"]


def _ensure_backlinks_indexes():
    """Idempotent index setup for the backlinks collection (safe to call per request)."""
    try:
        coll = backlinks_collection()
        coll.create_index("run_id", unique=True)
        coll.create_index([("started_at", DESCENDING)])
        coll.create_index("status")
        coll.create_index("site_id")
        coll.create_index(
            [
                ("site_id", ASCENDING),
                ("status", ASCENDING),
                ("started_at", DESCENDING),
            ]
        )
    except Exception as exc:
        print(f"[DASHBOARD BACKLINKS INDEX WARN] {exc!r}")


# =========================================================
# HELPERS
# =========================================================

def _utcnow():
    return datetime.now(timezone.utc)


def _as_datetime(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except Exception:
            return None
    return None


def _iso(value):
    dt = _as_datetime(value)
    return dt.isoformat() if dt else (str(value) if value else None)


def _norm_automation(value):
    return str(value or "").strip().upper()


def _fetch_runs(automation_type, cutoff):
    """Fetch runs since cutoff, filtered to automation (case/space tolerant)."""
    docs = list(
        runs_collection().find(
            {"started_at": {"$gte": cutoff}},
            {"_id": 0},
        )
    )
    return [
        d for d in docs
        if _norm_automation(d.get("automation_type")) == automation_type
    ]


def _build_summary(matched):
    total = len(matched)
    successful = sum(1 for r in matched if _norm_automation(r.get("status")) == "SUCCESS")
    failed = sum(1 for r in matched if _norm_automation(r.get("status")) == "FAILED")
    running = sum(1 for r in matched if _norm_automation(r.get("status")) == "RUNNING")
    interrupted = sum(1 for r in matched if _norm_automation(r.get("status")) == "INTERRUPTED")
    total_retries = sum(int(r.get("retry_count") or 0) for r in matched)
    unique_keywords = len(
        {str(r.get("original_keyword") or "").strip() for r in matched if r.get("original_keyword")}
    )
    summary = {
        "total_runs": total,
        "successful_runs": successful,
        "failed_runs": failed,
        "running_runs": running,
        "interrupted_runs": interrupted,
        "total_retries": total_retries,
        "unique_keywords": unique_keywords,
    }
    summary["success_rate"] = round((successful / total) * 100, 1) if total else 0
    return summary


def _build_daily(matched):
    buckets = {}
    for r in matched:
        dt = _as_datetime(r.get("started_at"))
        if not dt:
            continue
        key = dt.strftime("%Y-%m-%d")
        b = buckets.setdefault(key, {"total": 0, "success": 0, "failed": 0})
        b["total"] += 1
        if _norm_automation(r.get("status")) == "SUCCESS":
            b["success"] += 1
        elif _norm_automation(r.get("status")) == "FAILED":
            b["failed"] += 1
    return [
        {"day": k, "date": k, "label": k, **v}
        for k, v in sorted(buckets.items())
    ]


def _build_hourly(matched):
    buckets = {}
    for r in matched:
        dt = _as_datetime(r.get("started_at"))
        if not dt:
            continue
        hour = dt.replace(minute=0, second=0, microsecond=0)
        key = hour.isoformat()
        b = buckets.setdefault(key, {"total": 0, "success": 0, "failed": 0})
        b["total"] += 1
        if _norm_automation(r.get("status")) == "SUCCESS":
            b["success"] += 1
        elif _norm_automation(r.get("status")) == "FAILED":
            b["failed"] += 1
    return [
        {"day": k, "date": k, "label": k, "hour": k, **v}
        for k, v in sorted(buckets.items())
    ]


def _build_engines(matched):
    buckets = {}
    for r in matched:
        engine = (r.get("search_engine") or "").strip()
        if not engine or engine.lower() == "youtube":
            continue
        b = buckets.setdefault(engine, {"total": 0, "success": 0, "failed": 0})
        b["total"] += 1
        if _norm_automation(r.get("status")) == "SUCCESS":
            b["success"] += 1
        elif _norm_automation(r.get("status")) == "FAILED":
            b["failed"] += 1
    return [
        {"engine": k, **v}
        for k, v in sorted(buckets.items(), key=lambda kv: kv[1]["total"], reverse=True)
    ]


def _serialise_run(r):
    started = _as_datetime(r.get("started_at"))
    finished = _as_datetime(r.get("finished_at"))
    now = _utcnow()
    duration = None
    if started:
        duration = round(((finished or now) - started).total_seconds(), 1)
    return {
        "run_id": str(r.get("run_id") or ""),
        "automation_type": r.get("automation_type"),
        "original_keyword": r.get("original_keyword"),
        "search_keyword": r.get("search_keyword"),
        "browser_mode": r.get("browser_mode"),
        "target": r.get("target"),
        "search_engine": r.get("search_engine"),
        "started_at": _iso(started),
        "finished_at": _iso(finished),
        "status": r.get("status"),
        "success_count": int(r.get("success_count") or 0),
        "failure_count": int(r.get("failure_count") or 0),
        "retry_count": int(r.get("retry_count") or 0),
        "fallback_used": bool(r.get("fallback_used", False)),
        "duration_seconds": duration,
    }


# =========================================================
# BASIC ROUTES
# =========================================================

@app.get("/")
def index():
    return render_template("index.html")


def automation_filter(mode):
    mode = (mode or "YOUTUBE").upper()

    if mode not in {"YOUTUBE", "SEARCH", "BACKLINK"}:
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

        # Midnight (UTC) of (days-1) days ago, like
        # the old CURRENT_DATE - (days-1) SQL filter.
        today_midnight = _utcnow().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        cutoff = today_midnight - timedelta(days=days - 1)

        query_start = time.perf_counter()
        matched = _fetch_runs(automation_type, cutoff)
        print(
            "[DASHBOARD API]",
            f"matched={len(matched)} "
            f"fetch={(time.perf_counter() - query_start) * 1000:.1f}ms",
        )

        summary = _build_summary(matched)
        daily = _build_daily(matched)
        hourly = _build_hourly(matched)
        engines = _build_engines(matched)

        recent_docs = sorted(
            matched,
            key=lambda r: _as_datetime(r.get("started_at")) or _utcnow(),
            reverse=True,
        )[:50]
        recent = [_serialise_run(r) for r in recent_docs]

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
            "hourly": hourly,
            "engines": engines,
            "youtube": youtube,
            "recent": recent,
            "generated_at": _utcnow().isoformat(),
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
        docs = list(
            logs_collection()
            .find({"run_id": str(run_id)})
            .sort([("timestamp", ASCENDING), ("_id", ASCENDING)])
        )

        rows = []
        for d in docs:
            rows.append(
                {
                    "log_id": str(d.get("_id")),
                    "timestamp": _iso(d.get("timestamp")),
                    "level": d.get("level"),
                    "keyword": d.get("keyword"),
                    "search_engine": d.get("search_engine"),
                    "action": d.get("action"),
                    "event_status": d.get("event_status"),
                    "url": d.get("url"),
                    "error_message": d.get("error_message"),
                    "metadata": d.get("metadata") or {},
                    "message": d.get("message"),
                }
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
# BACKLINKS (dedicated collection)
# =========================================================

def _serialise_backlink(d):
    started = _as_datetime(d.get("started_at"))
    finished = _as_datetime(d.get("finished_at"))
    duration = d.get("duration_seconds")
    if duration is None and started:
        try:
            duration = round(((finished or _utcnow()) - started).total_seconds(), 1)
        except Exception:
            duration = None
    result_text = str(d.get("result_text") or "")
    return {
        "run_id": str(d.get("run_id") or ""),
        "site_id": d.get("site_id"),
        "site_url": d.get("site_url"),
        "target_url": d.get("target_url"),
        "target_title": d.get("target_title"),
        "keyword": d.get("keyword"),
        "category": d.get("category"),
        "status": d.get("status"),
        "result_text": result_text[:500],
        "result_xpath": d.get("result_xpath"),
        "detail": d.get("detail"),
        "browser_mode": d.get("browser_mode"),
        "started_at": _iso(started),
        "finished_at": _iso(finished),
        "duration_seconds": duration,
    }


def _build_backlink_summary(matched):
    total = len(matched)
    successful = sum(1 for r in matched if _norm_automation(r.get("status")) == "SUCCESS")
    failed = sum(1 for r in matched if _norm_automation(r.get("status")) == "FAILED")
    running = sum(1 for r in matched if _norm_automation(r.get("status")) == "RUNNING")
    interrupted = sum(1 for r in matched if _norm_automation(r.get("status")) == "INTERRUPTED")
    summary = {
        "total": total,
        "success": successful,
        "failed": failed,
        "running": running,
        "interrupted": interrupted,
    }
    summary["success_rate"] = round((successful / total) * 100, 1) if total else 0
    return summary


def _build_backlink_sites(matched):
    buckets = {}
    for r in matched:
        site_id = (r.get("site_id") or "unknown").strip()
        b = buckets.setdefault(
            site_id, {"site_id": site_id, "site_url": r.get("site_url") or "", "total": 0, "success": 0, "failed": 0}
        )
        if r.get("site_url") and not b["site_url"]:
            b["site_url"] = r.get("site_url")
        b["total"] += 1
        if _norm_automation(r.get("status")) == "SUCCESS":
            b["success"] += 1
        elif _norm_automation(r.get("status")) == "FAILED":
            b["failed"] += 1
    rows = sorted(buckets.values(), key=lambda v: v["total"], reverse=True)
    for row in rows:
        row["success_rate"] = round((row["success"] / row["total"]) * 100, 1) if row["total"] else 0
    return rows


@app.get("/api/backlinks")
def backlinks():
    request_start = time.perf_counter()
    try:
        days = max(1, min(int(request.args.get("days", 7)), 90))
        _ensure_backlinks_indexes()
        today_midnight = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff = today_midnight - timedelta(days=days - 1)
        docs = list(
            backlinks_collection()
            .find({"started_at": {"$gte": cutoff}}, {"_id": 0})
            .sort("started_at", DESCENDING)
            .limit(500)
        )
        summary = _build_backlink_summary(docs)
        sites = _build_backlink_sites(docs)
        recent = [_serialise_backlink(d) for d in docs[:200]]
        print(
            "[DASHBOARD BACKLINKS]",
            f"days={days} matched={len(docs)} "
            f"time={(time.perf_counter() - request_start) * 1000:.1f}ms",
        )
        return jsonify(
            {
                "summary": summary,
                "sites": sites,
                "recent": recent,
                "generated_at": _utcnow().isoformat(),
            }
        )
    except Exception as error:
        print("[DASHBOARD BACKLINKS ERROR]", repr(error))
        return jsonify({"error": str(error)}), 500


# --- Generate Backlinks job (runs backlink_main.py in background) ---

# RLock: the 409 branch serialises the job while already holding the lock.
_backlink_job_lock = threading.RLock()
_backlink_job = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "returncode": None,
    "output_tail": "",
    "error": None,
    "args": [],
    "stop_requested": False,
}

# Handle to the live backlink_main.py process (if any), guarded by _backlink_proc_lock.
_backlink_proc_lock = Lock()
_backlink_proc = None


def _run_backlink_job(cmd):
    global _backlink_proc
    started = _utcnow()
    try:
        with _backlink_proc_lock:
            _backlink_proc = subprocess.Popen(
                cmd,
                cwd=str(BASE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            print(f"[DASHBOARD BACKLINK JOB] pid={_backlink_proc.pid}")
        try:
            out, _ = _backlink_proc.communicate(timeout=6 * 3600)
            returncode = _backlink_proc.returncode
        except subprocess.TimeoutExpired:
            _kill_backlink_tree()
            out, _ = _backlink_proc.communicate()
            returncode = _backlink_proc.returncode
        tail = (out or "")[-6000:]
        with _backlink_job_lock:
            stopped = bool(_backlink_job.get("stop_requested"))
            if stopped:
                error = "Stopped by user."
            else:
                error = None if returncode == 0 else f"backlink_main.py exited with code {returncode}"
            _backlink_job.update(
                {
                    "running": False,
                    "finished_at": _utcnow().isoformat(),
                    "returncode": returncode,
                    "output_tail": tail,
                    "error": error,
                    "stop_requested": False,
                }
            )
    except Exception as exc:
        with _backlink_job_lock:
            _backlink_job.update(
                {
                    "running": False,
                    "finished_at": _utcnow().isoformat(),
                    "returncode": -1,
                    "error": str(exc),
                    "stop_requested": False,
                }
            )
    finally:
        with _backlink_proc_lock:
            _backlink_proc = None
    print(f"[DASHBOARD BACKLINK JOB] finished in {(_utcnow() - started).total_seconds():.1f}s")


def _kill_backlink_tree():
    """Terminate the running backlink_main.py process tree (best effort).

    Returns True when a live process was signalled, False when nothing ran.
    """
    with _backlink_proc_lock:
        proc = _backlink_proc
    if proc is None or proc.poll() is not None:
        return False
    try:
        if os.name == "nt":
            # /T kills the whole tree (browsers spawned by the script included).
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                timeout=20,
            )
        else:
            proc.terminate()
    except Exception as exc:
        print(f"[DASHBOARD BACKLINK STOP WARN] {exc!r}")
        try:
            proc.terminate()
        except Exception:
            pass
    try:
        proc.wait(timeout=20)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    return True


@app.post("/api/backlinks/generate")
def backlinks_generate():
    try:
        payload = request.get_json(silent=True) or {}
        sites = str(payload.get("sites") or request.args.get("sites") or "").strip()
        try:
            max_targets = int(payload.get("max_targets") or request.args.get("max_targets") or 0)
        except (TypeError, ValueError):
            max_targets = 0

        cmd = [sys.executable, "backlink_main.py"]
        if sites:
            cmd += ["--sites", sites]
        if max_targets and max_targets > 0:
            cmd += ["--max-targets", str(max_targets)]

        with _backlink_job_lock:
            if _backlink_job.get("running"):
                return (
                    jsonify({"error": "A backlink generation job is already running.", "job": _serialise_job()}),
                    409,
                )
            _backlink_job.update(
                {
                    "running": True,
                    "started_at": _utcnow().isoformat(),
                    "finished_at": None,
                    "returncode": None,
                    "output_tail": "",
                    "error": None,
                    "args": cmd[1:],
                    "stop_requested": False,
                }
            )

        worker = threading.Thread(target=_run_backlink_job, args=(cmd,), daemon=True, name="BacklinkGenerateJob")
        worker.start()
        print("[DASHBOARD BACKLINK JOB] started:", " ".join(cmd))
        return jsonify({"status": "started", "job": _serialise_job()}), 202
    except Exception as error:
        print("[DASHBOARD BACKLINK GENERATE ERROR]", repr(error))
        return jsonify({"error": str(error)}), 500


def _serialise_job():
    with _backlink_job_lock:
        return dict(_backlink_job)


@app.post("/api/backlinks/stop")
def backlinks_stop():
    """Stop a running backlink generation job (kills the process tree)."""
    try:
        with _backlink_job_lock:
            if not _backlink_job.get("running"):
                return jsonify({"status": "idle", "job": dict(_backlink_job)}), 200
            _backlink_job["stop_requested"] = True
        print("[DASHBOARD BACKLINK JOB] stop requested")
        killed = _kill_backlink_tree()
        with _backlink_job_lock:
            snapshot = dict(_backlink_job)
        # If the process was already gone, let the worker thread finish up;
        # report current state either way.
        return jsonify({"status": "stopping" if killed else "idle", "job": snapshot}), 202
    except Exception as error:
        print("[DASHBOARD BACKLINK STOP ERROR]", repr(error))
        return jsonify({"error": str(error)}), 500


@app.get("/api/backlinks/status")
def backlinks_status():
    try:
        return jsonify({"job": _serialise_job()})
    except Exception as error:
        return jsonify({"error": str(error)}), 500


# =========================================================
# HEALTH
# =========================================================

@app.get("/api/health")
def health():

    try:
        get_mongo_db().command("ping")

        return jsonify(
            {
                "status": "connected",
                "database": get_mongo_db().name,
                "environment": CURRENT_DB,
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
