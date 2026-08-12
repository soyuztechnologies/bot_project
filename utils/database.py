"""
database.py

Handles all database interactions for the bot project.
"""

import os
import psycopg2
from psycopg2 import pool
import logging, sys
from contextlib import contextmanager
from psycopg2.extras import register_uuid
from .logger import fallback_log

# Register the UUID adapter globally for all connections.
# This allows psycopg2 to handle Python's uuid.UUID objects correctly.
register_uuid()

logger = logging.getLogger(__name__)

# It's highly recommended to use environment variables for credentials
# instead of hardcoding them.
DB_NAME = os.getenv("DB_NAME", "seo_bot_db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "vipul123")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")

_db_available = False  # Assume DB is unavailable until a connection is confirmed
_connection_pool = None

def _initialize_pool():
    """Initializes the connection pool."""
    global _connection_pool
    if _connection_pool is None:
        try:
            _connection_pool = pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=10,  # Adjust maxconn based on number of parallel sessions
                dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD, host=DB_HOST, port=DB_PORT
            )
        except psycopg2.OperationalError as e:
            logger.warning(f"Failed to initialize database connection pool: {e}")


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
        yield conn
    except psycopg2.OperationalError as e:
        # This will be caught by check_db_connection or log_event
        # so we don't need to print here.
        raise
    finally:
        if conn and _connection_pool:
            _connection_pool.putconn(conn)


def initialize_database():
    """
    Ensures the necessary tables exist in the database. Creates 'bot_logs' and
    'bot_sessions' tables if they're not present.
    """
    create_logs_table_sql = """
    CREATE TABLE IF NOT EXISTS bot_logs (
        id SERIAL PRIMARY KEY,
        event_time TIMESTAMPTZ DEFAULT NOW(),
        session_id UUID,
        app_module VARCHAR(50), 
        level VARCHAR(50),
        keyword VARCHAR(255),
        engine VARCHAR(50),
        website VARCHAR(255),
        message TEXT,
        error_message TEXT
    );
    """
    create_sessions_table_sql = """
    CREATE TABLE IF NOT EXISTS bot_sessions (
        session_id UUID PRIMARY KEY,
        app_module VARCHAR(50),
        thread_id BIGINT,
        browser_mode VARCHAR(50),
        target_website VARCHAR(255),
        session_start_time TIMESTAMPTZ DEFAULT NOW(),
        session_end_time TIMESTAMPTZ,
        status VARCHAR(50),
        total_keywords INTEGER,
        successful_keywords INTEGER,
        failed_keywords INTEGER
    );
    """
    if _connection_pool is None:
        _initialize_pool()

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(create_logs_table_sql)
                cur.execute(create_sessions_table_sql)
                conn.commit()
        logger.info("Database initialized: 'bot_logs' and 'bot_sessions' tables are ready.")
    except psycopg2.Error as e:
        logger.error(f"Failed to initialize database: {e}")
        global _db_available
        _db_available = False


def create_session_record(session_id, app_module, thread_id, browser_mode, target_website):
    """
    Creates a new record for a session in the bot_sessions table.
    """
    sql = """
    INSERT INTO bot_sessions (session_id, app_module, thread_id, browser_mode, target_website)
    VALUES (%s, %s, %s, %s, %s);
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (session_id, app_module, thread_id, browser_mode, target_website))
                conn.commit()
    except psycopg2.Error as e:
        logger.error(f"Failed to create session record for {session_id}: {e}")


def update_session_record(session_id, session_end_time, status, total_keywords, successful_keywords, failed_keywords):
    """
    Updates an existing session record with completion details.
    """
    sql = """
    UPDATE bot_sessions
    SET session_end_time = %s,
        status = %s,
        total_keywords = %s,
        successful_keywords = %s,
        failed_keywords = %s
    WHERE session_id = %s;
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (session_end_time, status, total_keywords, successful_keywords, failed_keywords, session_id))
                conn.commit()
    except psycopg2.Error as e:
        logger.error(f"Failed to update session record for {session_id}: {e}")

def close_connection_pool():
    """Closes all connections in the pool."""
    global _connection_pool
    if _connection_pool:
        logger.info("Database connection pool closed.")
        _connection_pool.closeall()
        _connection_pool = None




def log_event(**kwargs):
    """
    Inserts a new event into the bot_logs table.
    If the database is unavailable, it writes to a fallback file log.
    Accepts keyword arguments that match column names in the bot_logs table.
    """
    global _db_available
    if not _db_available:
        fallback_log(kwargs)
        return

    columns = ', '.join(kwargs.keys())
    placeholders = ', '.join(['%s'] * len(kwargs))
    sql = f"INSERT INTO bot_logs ({columns}) VALUES ({placeholders});"

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(kwargs.values()))
                conn.commit()
    except psycopg2.Error as e:
        if _db_available:
            logger.warning(f"Database connection lost during log_event: {e}")
            logger.warning("Switching to fallback file logger for this and subsequent events.")
        _db_available = False
        fallback_log(kwargs)


class DatabaseHandler(logging.Handler):
    """
    A custom logging handler that sends log records to the PostgreSQL database.
    """

    def __init__(self):
        super().__init__()

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

            log_data = {
                "session_id": getattr(record, "session_id", None),
                "app_module": getattr(record, "app_module", None),
                "level": record.levelname,
                "keyword": getattr(record, "keyword", None),
                "engine": getattr(record, "engine", None),
                "website": getattr(record, "website", None),
                "message": record.getMessage(),
                "error_message": record.exc_text,
            }
            # Pass the complete log data to the event logger.
            # The log_event function will handle None values correctly.
            log_event(**log_data)
        except Exception:
            self.handleError(record)