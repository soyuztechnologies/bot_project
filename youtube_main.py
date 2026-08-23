"""
youtube_main.py

Entry point for YouTube Automation.
"""

import json
import logging
from pathlib import Path

from dotenv import load_dotenv  # type: ignore

from automation.youtube_session import start_parallel_sessions
from utils.database import (
    check_db_connection,
    DatabaseHandler,
    close_connection_pool,
    initialize_database,
)
from utils.logger import setup_logger

# ---------------------------------------------------------
# Base Configuration
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# JSON Loader
# ---------------------------------------------------------


def load_json(path):
    """
    Load and return JSON data from the given path.
    """

    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------


def main():
    """
    Run one complete YouTube automation cycle.

    Database logging is initialized before the automation starts.
    The automation itself follows the current File-1 flow.
    """

    db_initialized = False

    try:

        # -----------------------------------------------------
        # Logging Setup
        # -----------------------------------------------------

        setup_logger()

        # -----------------------------------------------------
        # Database Setup
        # -----------------------------------------------------

        try:

            initialize_database()
            db_initialized = True

            # Check whether the database is currently reachable.
            # Existing database implementation may switch to its
            # fallback logger when the connection is unavailable.
            check_db_connection()

            # Add database logging to the root logger so logs from
            # the complete application can be stored.
            logging.getLogger().addHandler(DatabaseHandler())

            logger.info("Database logging initialized successfully.")

        except Exception as db_error:

            # Do not stop the automation only because database
            # initialization failed.
            logger.error(
                f"Database initialization failed : {db_error}",
                exc_info=True,
            )

            logger.info("Continuing YouTube automation without " "database logging.")

        # -----------------------------------------------------
        # Load Configuration
        # -----------------------------------------------------

        config = load_json(BASE_DIR / "config.json")

        # -----------------------------------------------------
        # Load Keywords
        # -----------------------------------------------------

        keywords = load_json(BASE_DIR / config["files"]["keywords"])

        # -----------------------------------------------------
        # Start Message
        # -----------------------------------------------------

        print("=" * 60)
        print("YouTube Automation Started")
        print("=" * 60)

        print(f"Browsers : " f"{', '.join(config['browser']['browsers'])}")

        print(f"Sessions : " f"{config['sessions']['parallel']}")

        print(f"Keywords : {len(keywords)}")

        print("=" * 60)

        # -----------------------------------------------------
        # Start Parallel YouTube Sessions
        # -----------------------------------------------------

        stats = {
            "total": len(keywords),
            "success": [],
            "failed": [],
        }

        completed = start_parallel_sessions(
            keywords,
            config,
            stats,
        )

        # -----------------------------------------------------
        # Completion Status
        # -----------------------------------------------------

        if completed:

            print("\nCycle completed.")
            print("Automation completed successfully.")

            logger.info("YouTube automation cycle completed successfully.")

        else:

            print("\nAutomation stopped by user.")

            logger.info("YouTube automation stopped before completion.")

    except KeyboardInterrupt:

        print("\nAutomation stopped by user.")

        logger.info("YouTube automation stopped by user.")

    except Exception as error:

        print(f"\nUnexpected Error : {error}")

        logger.error(
            f"Unexpected YouTube automation error : {error}",
            exc_info=True,
        )

    finally:

        # -----------------------------------------------------
        # Database Cleanup
        # -----------------------------------------------------

        if db_initialized:

            try:

                close_connection_pool()

                logger.info("Database connection pool closed.")

            except Exception as db_error:

                logger.error(
                    f"Failed to close database connection pool : " f"{db_error}",
                    exc_info=True,
                )


# ---------------------------------------------------------
# Entry Point
# ---------------------------------------------------------

if __name__ == "__main__":
    main()
