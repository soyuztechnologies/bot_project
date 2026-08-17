"""
youtube_main.py

Entry point for YouTube Automation.
"""

import json
import time
import logging
from pathlib import Path
from dotenv import load_dotenv # type: ignore

from automation.youtube_session import start_parallel_sessions
from utils.database import check_db_connection, DatabaseHandler, close_connection_pool, initialize_database
from utils.logger import setup_logger


# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent


def load_json(path):

    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def print_summary(stats, config):
    """Prints a formatted summary of the automation results."""
    success_sessions = stats.get("success", [])
    failed_sessions = stats.get("failed", [])
    total_sessions = stats.get("total", len(success_sessions) + len(failed_sessions))
    success_count = len(success_sessions)
    failed_count = len(failed_sessions)

    # Sort for consistent output
    success_sessions.sort(key=lambda x: x["keyword"])
    failed_sessions.sort(key=lambda x: x["keyword"])

    # Use a mix of logger and print for a clean summary report
    logger.info("\n" + "=" * 50)
    logger.info(" Session Summary ".center(50, "="))

    # Using print here for the list to avoid logger's timestamp/level prefixes
    for session in success_sessions:
        print(f"✓ {session['keyword']:<30} [{session['engine']}]")

    if success_sessions and failed_sessions:
        print()

    for session in failed_sessions:
        print(f"✗ {session['keyword']:<30} [{session['engine']}]")

    logger.info("\n" + "-" * 50)
    logger.info(f"Browser Mode: {config['browser']['mode'].capitalize()}")
    logger.info(f"Total   : {total_sessions}")
    logger.info(f"Success : {success_count}")
    logger.info(f"Failed  : {failed_count}")
    logger.info("=" * 50)


def main():
    """Main function to run the YouTube automation bot."""
    try:
        setup_logger()
        # Initialize database and then check the connection
        initialize_database()

        # Add the custom database handler to the root logger.
        # This will capture logs from the entire application.
        logging.getLogger().addHandler(DatabaseHandler())

        while True:
            try:
                # Check database connection at the start of each cycle
                # It will switch to a fallback file logger if connection fails.
                check_db_connection()
                config = load_json(BASE_DIR / "config.json")

                keywords = load_json(
                    BASE_DIR / config["files"]["keywords"]
                )

                logger.info("=" * 60)
                logger.info("YouTube Automation Started")
                logger.info("=" * 60)
                logger.info(f"Browsers : {', '.join(config['browser']['browsers'])}")
                logger.info(f"Sessions : {config['sessions']['parallel']}")
                logger.info(f"Keywords : {len(keywords)}")
                logger.info("=" * 60)

                stats = start_parallel_sessions(
                    keywords,
                    config,
                )
                print_summary(stats, config)

                logger.info("\nCycle completed.")
                logger.info("Waiting 5 minutes before next cycle...\n")

                time.sleep(300)

            except KeyboardInterrupt:
                logger.info("\nAutomation stopped by user.")
                break

            except Exception as error:
                logger.error(f"\nUnexpected Error : {error}", exc_info=True)
                logger.info("Restarting automation in 30 seconds...\n")
                time.sleep(30)
    except KeyboardInterrupt:
        logger.info("\nYouTube automation stopped by user.")
    except Exception as error:
        logger.error(f"Fatal YouTube automation error: {error}", exc_info=True)
    finally:
        logger.info("YouTube Automation Project Finished.")
        close_connection_pool()

if __name__ == "__main__":
    main()
