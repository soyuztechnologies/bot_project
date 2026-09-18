"""
database.py

MongoDB (local / Atlas) interactions for the bot project, including
client management, collection/index setup, and logging.

DB selection:
  config.json -> database.current_db  (e.g. "local" or "atlas")
  config.json -> database.db[current_db]  = env var name holding the URI
  .env       -> MONGO_URI_LOCAL / MONGO_URI_ATLAS
"""

import os
import logging
import json
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone

from dotenv import load_dotenv
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError

from .logger import fallback_log

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# Database Configuration (config.json -> .env)
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parents[1]

with open(
    BASE_DIR / "config.json",
    encoding="utf-8",
) as file:
    CONFIG = json.load(file)

DATABASE_CONFIG = CONFIG.get("database", {})

CURRENT_DB = DATABASE_CONFIG.get(
    "current_db",
    "atlas",
)

DB_CONNECTION_ENV = DATABASE_CONFIG.get(
    "db",
    {},
).get(CURRENT_DB)

if not DB_CONNECTION_ENV:
    raise ValueError(
        "Database connection is not configured "
        f"for '{CURRENT_DB}'. "
        "Set database.current_db and database.db in config.json."
    )

MONGO_URI = os.getenv(DB_CONNECTION_ENV)

if not MONGO_URI:
    raise ValueError(
        "Environment variable "
        f"'{DB_CONNECTION_ENV}' is not set. "
        "Set it in .env "
        "(e.g. MONGO_URI_LOCAL / MONGO_URI_ATLAS)."
    )

# Optional explicit DB name override, otherwise taken from the
# URI path, otherwise seo_bot_db.
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "").strip() or None

logger.info(
    f"Database environment selected: {CURRENT_DB} "
    f"(env: {DB_CONNECTION_ENV})"
)

_db_available = False  # Assume DB is unavailable until ping succeeds
_client = None
_db = None


def _resolve_db_name(client, uri):
    if MONGO_DB_NAME:
        return MONGO_DB_NAME
    try:
        default_db = client.get_default_database()
        if default_db is not None:
            return default_db.name
    except Exception:
        pass
    # Fallback: parse trailing path from URI, else default name.
    try:
        path = uri.split("?", 1)[0].rsplit("/", 1)[-1]
        if path and not path.startswith("mongodb"):
            return path
    except Exception:
        pass
    return os.getenv("MONGO_DB_FALLBACK", "seo_bot_db")


def _get_client():
    """Lazily create the shared MongoClient."""
    global _client, _db
    if _client is None:
        _client = MongoClient(
            MONGO_URI,
            serverSelectionTimeoutMS=int(
                os.getenv("MONGO_SERVER_SELECTION_TIMEOUT_MS", "5000")
            ),
        )
        _db = _client[_resolve_db_name(_client, MONGO_URI)]
    return _client


def get_database():
    """Return the selected MongoDB database."""
    _get_client()
    return _db


def get_runs_collection():
    return get_database()["automation_runs"]


def get_logs_collection():
    return get_database()["automation_logs"]


def get_backlinks_collection():
    """Dedicated collection for backlink (ping submission) results.

    One flat document per (ping site x target url) submission, so the
    dashboard can render backlink tables without joining runs/logs.
    """
    return get_database()["backlinks"]


@contextmanager
def get_db_connection():
    """Compat context manager yielding the MongoDB database."""
    yield get_database()


def _json_safe(value):
    """Convert logging context values into JSON-friendly values."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def _utcnow():
    return datetime.now(timezone.utc)


def _as_utc(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            # Naive datetimes come from datetime.now() in local time
            # (e.g. IST). Interpret as local, then convert to UTC.
            # Assuming UTC here added +5:30 to every duration.
            local_tz = datetime.now().astimezone().tzinfo
            return value.replace(tzinfo=local_tz).astimezone(timezone.utc)
        return value
    return _utcnow()


def check_db_connection():
    """
    Ping MongoDB. Sets a global flag and logs status.
    """
    global _db_available
    try:
        _get_client().admin.command("ping")
        if not _db_available:
            logger.info("Database connection successful (MongoDB).")
        _db_available = True
        return True
    except (ServerSelectionTimeoutError, PyMongoError, Exception) as e:
        if _db_available:
            logger.warning(
                f"Database connection failed: {e}. "
                "Switching to fallback file logger."
            )
        _db_available = False
        return False


def initialize_database():
    """
    Ensure collections + indexes exist for
    'automation_runs', 'automation_logs' and 'backlinks'.
    """
    global _db_available
    try:
        runs = get_runs_collection()
        logs = get_logs_collection()
        backlinks = get_backlinks_collection()

        runs.create_index("run_id", unique=True)
        runs.create_index([("started_at", DESCENDING)])
        runs.create_index("status")
        runs.create_index("flow_type")
        runs.create_index(
            [
                ("automation_type", ASCENDING),
                ("status", ASCENDING),
                ("started_at", DESCENDING),
            ]
        )
        runs.create_index(
            [
                ("search_engine", ASCENDING),
                ("status", ASCENDING),
                ("started_at", DESCENDING),
            ]
        )

        logs.create_index([("run_id", ASCENDING)])
        logs.create_index([("timestamp", ASCENDING)])
        logs.create_index("level")
        logs.create_index(
            [("run_id", ASCENDING), ("timestamp", ASCENDING)]
        )
        logs.create_index(
            [("action", ASCENDING), ("event_status", ASCENDING)]
        )

        backlinks.create_index("run_id", unique=True)
        backlinks.create_index([("started_at", DESCENDING)])
        backlinks.create_index("status")
        backlinks.create_index("site_id")
        backlinks.create_index(
            [
                ("site_id", ASCENDING),
                ("status", ASCENDING),
                ("started_at", DESCENDING),
            ]
        )

        _db_available = True
        logger.info(
            "Database initialized: 'automation_runs', "
            "'automation_logs' and 'backlinks' collections are ready (MongoDB)."
        )
    except (PyMongoError, Exception) as e:
        logger.error(f"Failed to initialize database: {e}")
        _db_available = False


def create_automation_run(run_id, automation_type, original_keyword, search_keyword, browser_mode, target, search_engine=None, flow_type=None, user_name=None):
    """
    Insert a new automation run document. run_id stored as string.
    flow_type is YouTube-only ('youtube_first' / 'search_engine_first').
    """
    try:
        get_runs_collection().insert_one(
            {
                "run_id": str(run_id),
                "automation_type": automation_type,
                "original_keyword": original_keyword,
                "search_keyword": search_keyword,
                "fallback_used": False,
                "browser_mode": browser_mode,
                "target": target,
                "search_engine": search_engine,
                "flow_type": flow_type,
                "user_name": user_name,
                "captcha_encountered": False,
                "started_at": _utcnow(),
                "finished_at": None,
                "status": "RUNNING",
                "success_count": 0,
                "failure_count": 0,
                "retry_count": 0,
            }
        )
    except (PyMongoError, Exception) as e:
        logger.error(f"Failed to create automation run record for {run_id}: {e}")


def update_automation_run(run_id, finished_at, status, success_count, failure_count, retry_count, fallback_used=False, search_keyword=None, search_engine=None, browser_mode=None, flow_type=None, captcha_encountered=None):
    """
    Update a run document. None values leave existing fields untouched.
    """
    if not isinstance(finished_at, datetime):
        finished_at = _utcnow()
    else:
        finished_at = _as_utc(finished_at)

    update = {
        "finished_at": finished_at,
        "status": status,
        "success_count": success_count,
        "failure_count": failure_count,
        "retry_count": retry_count,
        "fallback_used": fallback_used,
    }
    if search_keyword is not None:
        update["search_keyword"] = search_keyword
    if search_engine is not None:
        update["search_engine"] = search_engine
    if browser_mode is not None:
        update["browser_mode"] = browser_mode
    if flow_type is not None:
        update["flow_type"] = flow_type
    if captcha_encountered is not None:
        update["captcha_encountered"] = captcha_encountered

    try:
        get_runs_collection().update_one(
            {"run_id": str(run_id)},
            {"$set": update},
        )
    except (PyMongoError, Exception) as e:
        logger.error(f"Failed to update automation run record for {run_id}: {e}")


def reconcile_stale_runs(timeout_minutes=30, batch_limit=500):
    """Flip old RUNNING runs to INTERRUPTED. Never raises.

    Covers process kills / Ctrl+C during DB outage / any early-return
    path that skipped the terminal update: the console summary comes
    from in-memory stats, but the DB row stays RUNNING forever.
    Called once at startup; also fixes rows stuck by previous runs.
    Returns number of rows reconciled (0 on any failure).
    """
    from datetime import timedelta

    try:
        cutoff = _utcnow() - timedelta(minutes=max(1, int(timeout_minutes)))
    except Exception:
        from datetime import timedelta as _td

        cutoff = _utcnow() - _td(minutes=30)
    try:
        result = get_runs_collection().update_many(
            {"status": "RUNNING", "started_at": {"$lt": cutoff}},
            {
                "$set": {
                    "status": "INTERRUPTED",
                    "finished_at": _utcnow(),
                    "stale_reconciled": True,
                }
            },
        )
        matched = getattr(result, "matched_count", 0) or 0
        if matched:
            try:
                logger.warning(
                    f"Reconciled {matched} stale RUNNING automation run(s) "
                    f"older than {cutoff.isoformat()} to INTERRUPTED."
                )
            except Exception:
                pass
        return matched
    except (PyMongoError, Exception) as e:
        try:
            logger.warning(f"Stale-run reconciliation skipped: {e}")
        except Exception:
            pass
        return 0


def save_backlink_submission(doc):
    """Upsert one flat backlink result document (keyed by run_id).

    Expected keys: run_id, site_id, site_url, target_url, target_title,
    keyword, category, status, result_text, result_xpath, detail,
    browser_mode, started_at, finished_at, duration_seconds.
    Never raises — backlink persistence must not break the automation.
    """
    try:
        payload = dict(doc or {})
        payload["run_id"] = str(payload.get("run_id") or "")
        if not payload["run_id"]:
            logger.error("Refusing to save backlink submission without run_id.")
            return False
        payload["updated_at"] = _utcnow()
        payload.setdefault("started_at", payload["updated_at"])
        get_backlinks_collection().update_one(
            {"run_id": payload["run_id"]},
            {"$set": payload},
            upsert=True,
        )
        return True
    except (PyMongoError, Exception) as e:
        logger.error(f"Failed to save backlink submission: {e}")
        return False


def close_connection_pool():
    """Close the shared MongoClient (kept name for compatibility).

    Never raises and never blocks shutdown: ``MongoClient.close()``
    performs network I/O (``_end_sessions`` -> DNS ``getaddrinfo``)
    which hangs when the VPN just broke the network. Run it in a
    daemon thread with a short timeout and swallow BaseException
    (including KeyboardInterrupt arriving during finally).
    """
    global _client, _db
    client, _client = _client, None
    _db = None
    if client is None:
        return
    import threading

    def _do_close():
        try:
            client.close()
        except BaseException:
            pass

    worker = threading.Thread(target=_do_close, daemon=True)
    try:
        worker.start()
    except BaseException:
        return
    try:
        worker.join(timeout=3.0)
    except BaseException:
        pass
    if worker.is_alive():
        # Still hanging on DNS/network: abandon it, process can exit.
        try:
            logger.warning(
                "Database close timed out (network down?), "
                "skipping blocking close."
            )
        except Exception:
            pass
        return
    try:
        logger.info("Database connection closed (MongoDB).")
    except Exception:
        pass


# Alias with Mongo naming.
close_mongo_client = close_connection_pool


def log_event(
    run_id,
    timestamp,
    level,
    keyword,
    search_engine,
    message,
    action=None,
    event_status=None,
    url=None,
    error_message=None,
    metadata=None,
    flow_type=None,
):
    """
    Insert a log document into automation_logs.
    Falls back to file log when MongoDB is unavailable.
    """
    global _db_available
    if not isinstance(timestamp, datetime):
        timestamp = _utcnow()
    else:
        timestamp = _as_utc(timestamp)

    event_data = {
        "run_id": str(run_id),
        "timestamp": timestamp,
        "level": level,
        "keyword": keyword,
        "search_engine": search_engine,
        "action": action,
        "event_status": event_status,
        "url": url,
        "error_message": error_message,
        "metadata": metadata or {},
        "message": message,
        "flow_type": flow_type,
    }
    if not _db_available:
        fallback_log(event_data)
        return

    try:
        get_logs_collection().insert_one(event_data)
    except (PyMongoError, Exception) as e:
        if _db_available:
            logger.warning(f"Database connection lost during log_event: {e}")
            logger.warning("Switching to fallback file logger for this and subsequent events.")
        _db_available = False
        fallback_log(event_data)


class DatabaseHandler(logging.Handler):
    """
    A custom logging handler that sends log records to MongoDB.
    """

    def __init__(self):
        super().__init__()

    def _metadata_from_record(self, record):
        metadata_keys = (
            "search_keyword",
            "app_module",
            "website",
            "target",
            "thread_id",
        )
        metadata = {}
        for key in metadata_keys:
            value = getattr(record, key, None)
            if value is not None:
                metadata[key] = _json_safe(value)
        return metadata

    def emit(self, record):
        """
        Formats the log record and sends it to the database via log_event.
        It expects 'keyword' and 'engine' to be in the record's __dict__
        if they are to be logged.
        """
        try:
            # Prevent infinite recursion if the database logging itself fails
            if record.name == __name__:
                return

            # Extract run_id from the LoggerAdapter's extra context
            run_id = getattr(record, "session_id", None)

            # If there's no run_id, it's a general log, not a session-specific one.
            # Do not log it to the database. It will still be handled by other handlers (e.g., StreamHandler).
            if run_id is None:
                return

            keyword = getattr(record, "keyword", None)
            search_engine = getattr(record, "engine", None)  # 'engine' is used for search engines, 'youtube' for youtube
            # YouTube-only flow ('youtube_first' / 'search_engine_first').
            # SessionLoggerAdapter carries it as 'flow'; accept 'flow_type' too.
            flow_type = getattr(record, "flow_type", None) or getattr(record, "flow", None)
            action = getattr(record, "action", None)
            event_status = getattr(record, "status", None)
            url = getattr(record, "url", None)
            error_message = getattr(record, "error_message", None)
            metadata = self._metadata_from_record(record)

            # Use record.created for timestamp (float seconds since epoch) and convert to datetime
            timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc)

            message = record.getMessage()  # Use unformatted message

            log_event(
                run_id,
                timestamp,
                record.levelname,
                keyword,
                search_engine,
                message,
                action=action,
                event_status=event_status,
                url=url,
                error_message=error_message,
                metadata=metadata,
                flow_type=flow_type,
            )
        except Exception:
            self.handleError(record)
