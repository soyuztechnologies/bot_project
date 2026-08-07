"""
database.py

Handles all database interactions for the bot project.
"""

import os
import psycopg2
import logging
from contextlib import contextmanager
from .logger import fallback_log

logger = logging.getLogger(__name__)

# It's highly recommended to use environment variables for credentials
# instead of hardcoding them.
DB_NAME = os.getenv("DB_NAME", "seo_bot_db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")

_db_available = True  # Assume DB is available until a connection fails


def check_db_connection():
    """
    Checks if a connection to the database can be established.
    Sets a global flag based on the result and logs status.
    """
    global _db_available
    try:
        with get_db_connection():
            # The context manager handles the connection. If it succeeds, we're good.
            pass
        if not _db_available:
            logger.info("Database connection has been restored.")
        _db_available = True
        return True
    except psycopg2.OperationalError:
        if _db_available:
            logger.warning("Database connection failed. Switching to fallback file logger.")
        _db_available = False
        return False


@contextmanager
def get_db_connection():
    """Context manager for a temporary database connection."""
    conn = None
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        yield conn
    except psycopg2.OperationalError as e:
        # This will be caught by check_db_connection or log_event
        # so we don't need to print here.
        raise
    finally:
        if conn:
            conn.close()


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
    except psycopg2.OperationalError as e:
        if _db_available:
            logger.warning(f"Database connection lost during log_event: {e}")
            logger.warning("Switching to fallback file logger for this and subsequent events.")
        _db_available = False
        fallback_log(kwargs)