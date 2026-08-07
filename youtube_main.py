"""
youtube_main.py

Entry point for YouTube Automation.
"""

import json
import time
import logging
from pathlib import Path
from dotenv import load_dotenv

from automation.youtube_session import start_parallel_sessions
from utils.database import check_db_connection
from utils.logger import setup_logger


# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent


def load_json(path):

    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def main():
    setup_logger()

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

            start_parallel_sessions(
                keywords,
                config,
            )

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

if __name__ == "__main__":
    main()