"""
youtube_main.py

Entry point for YouTube Automation.

This merged version keeps the original YouTube main flow and adds
Vipul's database initialization, application logging, and cleanup.
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

    Keeps the original main flow:
    - Load config
    - Load keywords
    - Load search engines
    - Start parallel sessions

    Adds Vipul's:
    - .env loading
    - application logger setup
    - database initialization
    - database connection check
    - database logging handler
    - database cleanup
    """

    db_initialized = False
    database_handler = None

    try:

        # -----------------------------------------------------
        # Logging Setup
        # -----------------------------------------------------

        try:
            setup_logger()
        except Exception as log_error:
            # Logging setup should not stop the automation.
            print(f"Logger setup failed : {log_error}")

        # -----------------------------------------------------
        # Database Setup
        # -----------------------------------------------------

        try:

            initialize_database()
            db_initialized = True

            # Check whether database is reachable.
            check_db_connection()

            # Add database logging to the root logger.
            database_handler = DatabaseHandler()
            logging.getLogger().addHandler(database_handler)

            logger.info(
                "Database logging initialized successfully."
            )

        except Exception as db_error:

            # Database failure must NOT stop YouTube automation.
            logger.error(
                f"Database initialization failed : {db_error}",
                exc_info=True,
            )

            logger.info(
                "Continuing YouTube automation without database logging."
            )

        # -----------------------------------------------------
        # Load Configuration
        # -----------------------------------------------------

        config = load_json(
            BASE_DIR / "config.json"
        )

        # -----------------------------------------------------
        # Load Keywords
        # -----------------------------------------------------

        keywords = load_json(
            BASE_DIR / config["files"]["keywords"]
        )

        # -----------------------------------------------------
        # Load Search Engines
        # -----------------------------------------------------

        search_engines = load_json(
            BASE_DIR / config["files"]["searchEngines"]
        )

        # -----------------------------------------------------
        # Start Message
        # -----------------------------------------------------

        print("=" * 60)
        print("YouTube Automation Started")
        print("=" * 60)

        print(
            f"Browsers : "
            f"{', '.join(config['browser']['browsers'])}"
        )

        print(
            f"Sessions : "
            f"{config['sessions']['parallel']}"
        )

        print(
            f"Keywords : {len(keywords)}"
        )

        print("=" * 60)

        logger.info(
            "YouTube automation started."
        )

        # -----------------------------------------------------
        # Start Parallel YouTube Sessions
        # -----------------------------------------------------
        #
        # IMPORTANT:
        # The merged youtube_session.py keeps the original
        # function signature:
        #
        # start_parallel_sessions(
        #     keywords,
        #     config,
        #     search_engines
        # )
        #
        # Therefore we pass search_engines here instead of
        # Vipul's stats dictionary.
        #
        # Database session records are handled inside
        # youtube_session.py.
        # -----------------------------------------------------

        completed = start_parallel_sessions(
            keywords,
            config,
            search_engines,
        )

        # -----------------------------------------------------
        # Completion Status
        # -----------------------------------------------------

        if completed:

            print("\nCycle completed.")
            print(
                "Automation completed successfully."
            )

            logger.info(
                "YouTube automation cycle completed successfully."
            )

        else:

            print(
                "\nAutomation stopped by user."
            )

            logger.info(
                "YouTube automation stopped before completion."
            )

    except KeyboardInterrupt:

        print(
            "\nAutomation stopped by user."
        )

        logger.info(
            "YouTube automation stopped by user."
        )

    except Exception as error:

        print(
            f"\nUnexpected Error : {error}"
        )

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

                logger.info(
                    "Database connection pool closed."
                )

            except Exception as db_error:

                logger.error(
                    f"Failed to close database connection pool : "
                    f"{db_error}",
                    exc_info=True,
                )


# ---------------------------------------------------------
# Entry Point
# ---------------------------------------------------------

if __name__ == "__main__":
    main()
