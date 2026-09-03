"""
database.py

Handles all database interactions for the bot project, including
connection pooling, schema management, and logging.
"""

import os
import psycopg2
from psycopg2 import pool
import logging
import json
from pathlib import Path
from contextlib import contextmanager
from dotenv import load_dotenv
from psycopg2.extras import Json, register_uuid
from .logger import fallback_log
from datetime import datetime

load_dotenv()

# Register the UUID adapter globally for all connections.
# This allows psycopg2 to handle Python's uuid.UUID objects correctly.
register_uuid()

logger = logging.getLogger(__name__)

# It's highly recommended to use environment variables for credentials
# instead of hardcoding them.
# ---------------------------------------------------------
# Database Configuration
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
    "public",
)

DB_CONNECTION_ENV = DATABASE_CONFIG.get(
    "db",
    {},
).get(CURRENT_DB)

if not DB_CONNECTION_ENV:
    raise ValueError(
        f"Database connection is not configured "
        f"for '{CURRENT_DB}'"
    )

DB_CONNECTION_URL = os.getenv(
    DB_CONNECTION_ENV
)

if not DB_CONNECTION_URL:
    raise ValueError(
        f"Environment variable "
        f"'{DB_CONNECTION_ENV}' is not set"
    )

logger.info(
    f"Database environment selected: {CURRENT_DB}"
)

_db_available = False  # Assume DB is unavailable until a connection is confirmed
_connection_pool = None

def _initialize_pool():
    """Initializes the connection pool."""
    global _connection_pool
    if _connection_pool is None:
        try:
            _connection_pool = pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=10,
                dsn=DB_CONNECTION_URL,
            )
        except psycopg2.OperationalError as e:
            logger.warning(f"Failed to initialize database connection pool: {e}")


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


def check_db_connection():
    """
    Checks if a connection to the database can be established.
    Sets a global flag based on the result and logs status.
    """
    global _db_available
    if _connection_pool is None:
        _initialize_pool()

    try:
        with get_db_connection():
            logger.info("Database connection successful.")
        _db_available = True
        return True
    except psycopg2.OperationalError as e:
        if _db_available:
            # Only log the warning once when it transitions from available to unavailable
            logger.warning(f"Database connection failed: {e}. Switching to fallback file logger.")
        _db_available = False
        return False


@contextmanager
def get_db_connection():
    """Context manager for a temporary database connection."""
    conn = None
    if _connection_pool is None:
        raise psycopg2.OperationalError("Connection pool is not initialized.")
    try:
        conn = _connection_pool.getconn()
        with conn.cursor() as cur:
            cur.execute("SET TIMEZONE TO 'Asia/Kolkata';")
        yield conn
        conn.commit()
    except psycopg2.Error:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn and _connection_pool:
            _connection_pool.putconn(conn)


def initialize_database():
    """
    Ensures the necessary tables exist in the database. Creates 'automation_runs' and
    'automation_logs' tables if they're not present.
    """
    global _db_available

    create_runs_table_sql = """
    CREATE TABLE IF NOT EXISTS automation_runs (
        run_id UUID PRIMARY KEY,
        automation_type VARCHAR(50) NOT NULL, -- 'SEARCH' or 'YOUTUBE'
        original_keyword VARCHAR(255) NOT NULL,
        search_keyword VARCHAR(255) NOT NULL,
        fallback_used BOOLEAN NOT NULL DEFAULT FALSE,
        browser_mode VARCHAR(50) NOT NULL,
        target VARCHAR(255), -- Target domain for search, target channel for YouTube
        search_engine VARCHAR(50), -- Specific search engine used (for SEARCH type)
        started_at TIMESTAMPTZ NOT NULL,
        finished_at TIMESTAMPTZ,
        status VARCHAR(50) NOT NULL, -- 'RUNNING', 'SUCCESS', 'FAILED', 'INTERRUPTED'
        success_count INTEGER DEFAULT 0, -- 1 if keyword attempt was successful, 0 otherwise
        failure_count INTEGER DEFAULT 0, -- 1 if keyword attempt failed, 0 otherwise
        retry_count INTEGER DEFAULT 0 -- Number of retries for this specific keyword operation
    );
    CREATE INDEX IF NOT EXISTS idx_automation_runs_started_at ON automation_runs (started_at);
    CREATE INDEX IF NOT EXISTS idx_automation_runs_status ON automation_runs (status);
    CREATE INDEX IF NOT EXISTS idx_automation_runs_type_status_started_at ON automation_runs (automation_type, status, started_at DESC);
    CREATE INDEX IF NOT EXISTS idx_automation_runs_engine_status_started_at ON automation_runs (search_engine, status, started_at DESC);
    """
    create_logs_table_sql = """
    CREATE TABLE IF NOT EXISTS automation_logs (
        log_id SERIAL PRIMARY KEY,
        run_id UUID NOT NULL REFERENCES automation_runs(run_id) ON DELETE CASCADE,
        timestamp TIMESTAMPTZ NOT NULL,
        level VARCHAR(50) NOT NULL,
        keyword VARCHAR(255), -- Contextual keyword for the log entry
        search_engine VARCHAR(50), -- Contextual search engine for the log entry
        action VARCHAR(80), -- Structured step name, e.g. KEYWORD_SEARCH
        event_status VARCHAR(50), -- Structured step status, e.g. RUNNING/SUCCESS/FAILED
        url TEXT,
        error_message TEXT,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        message TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_automation_logs_run_id ON automation_logs (run_id);
    CREATE INDEX IF NOT EXISTS idx_automation_logs_timestamp ON automation_logs (timestamp);
    CREATE INDEX IF NOT EXISTS idx_automation_logs_level ON automation_logs (level);
    CREATE INDEX IF NOT EXISTS idx_automation_logs_run_timestamp ON automation_logs (run_id, timestamp);
    """
    migrate_runs_table_sql = """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'automation_runs'
              AND column_name = 'target_website'
        ) AND NOT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'automation_runs'
              AND column_name = 'target'
        ) THEN
            ALTER TABLE automation_runs RENAME COLUMN target_website TO target;
        END IF;
    END $$;
    """
    migrate_logs_table_sql = """
    ALTER TABLE automation_logs ADD COLUMN IF NOT EXISTS action VARCHAR(80);
    ALTER TABLE automation_logs ADD COLUMN IF NOT EXISTS event_status VARCHAR(50);
    ALTER TABLE automation_logs ADD COLUMN IF NOT EXISTS url TEXT;
    ALTER TABLE automation_logs ADD COLUMN IF NOT EXISTS error_message TEXT;
    ALTER TABLE automation_logs ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
    ALTER TABLE automation_logs DROP COLUMN IF EXISTS duration_ms;
    ALTER TABLE automation_logs DROP COLUMN IF EXISTS retry_attempt;
    CREATE INDEX IF NOT EXISTS idx_automation_logs_action_status ON automation_logs (action, event_status);
    """
    if _connection_pool is None:
        _initialize_pool()

    try:
        with get_db_connection() as conn:
            # Drop old tables if they exist to ensure clean migration
            with conn.cursor() as cur:
                cur.execute("DROP TABLE IF EXISTS bot_logs CASCADE;")
                cur.execute("DROP TABLE IF EXISTS bot_sessions CASCADE;")
                conn.commit()

            with conn.cursor() as cur:
                cur.execute(create_runs_table_sql)
                cur.execute(migrate_runs_table_sql)
                cur.execute(create_logs_table_sql)
                cur.execute(migrate_logs_table_sql)
                conn.commit()
        _db_available = True
        logger.info("Database initialized: 'automation_runs' and 'automation_logs' tables are ready.")
    except psycopg2.Error as e:
        logger.error(f"Failed to initialize database: {e}")
        _db_available = False


def create_automation_run(run_id, automation_type, original_keyword, search_keyword, browser_mode, target, search_engine=None):
    """
    Creates a new record for an automation run in the automation_runs table.
    """
    sql = """
    INSERT INTO automation_runs (run_id, automation_type, original_keyword, search_keyword, browser_mode, target, search_engine, started_at, status)
    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), %s);
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (run_id, automation_type, original_keyword, search_keyword, browser_mode, target, search_engine, 'RUNNING'))
                conn.commit()
    except psycopg2.Error as e:
        logger.error(f"Failed to create automation run record for {run_id}: {e}")


def update_automation_run(run_id, finished_at, status, success_count, failure_count, retry_count, fallback_used=False, search_keyword=None):
    """
    Updates an existing automation run record with completion details.
    """
    # Ensure finished_at is a datetime object
    if not isinstance(finished_at, datetime):
        finished_at = datetime.now()
 
    sql = """
    UPDATE automation_runs
    SET finished_at = %s,
        status = %s,
        success_count = %s,
        failure_count = %s,
        retry_count = %s,
        fallback_used = %s,
        search_keyword = COALESCE(%s, search_keyword)
    WHERE run_id = %s;
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (finished_at, status, success_count, failure_count, retry_count, fallback_used, search_keyword, run_id))
                conn.commit()
    except psycopg2.Error as e:
        logger.error(f"Failed to update automation run record for {run_id}: {e}")

def close_connection_pool():
    """Closes all connections in the pool."""
    global _connection_pool
    if _connection_pool:
        logger.info("Database connection pool closed.")
        _connection_pool.closeall()
        _connection_pool = None

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
):
    """
    Inserts a new event into the automation_logs table.
    If the database is unavailable, it writes to a fallback file log.
    """
    global _db_available
    event_data = {
        "run_id": run_id,
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
    }
    if not _db_available:
        fallback_log(event_data)
        return

    sql = """
    INSERT INTO automation_logs (
        run_id,
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
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
    """

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        run_id,
                        timestamp,
                        level,
                        keyword,
                        search_engine,
                        action,
                        event_status,
                        url,
                        error_message,
                        Json(metadata or {}),
                        message,
                    ),
                )
                conn.commit()
    except psycopg2.Error as e:
        if _db_available:
            logger.warning(f"Database connection lost during log_event: {e}")
            logger.warning("Switching to fallback file logger for this and subsequent events.")
        _db_available = False
        fallback_log(event_data)


class DatabaseHandler(logging.Handler):
    """
    A custom logging handler that sends log records to the PostgreSQL database.
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
            search_engine = getattr(record, "engine", None) # 'engine' is used for search engines, 'youtube' for youtube
            action = getattr(record, "action", None)
            event_status = getattr(record, "status", None)
            url = getattr(record, "url", None)
            error_message = getattr(record, "error_message", None)
            metadata = self._metadata_from_record(record)

            # Use record.created for timestamp (float seconds since epoch) and convert to datetime
            timestamp = datetime.fromtimestamp(record.created)

            message = record.getMessage() # Use unformatted message

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
            )
        except Exception:
            self.handleError(record)
