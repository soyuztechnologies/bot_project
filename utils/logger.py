import logging
import sys


def setup_logger():
    """
    Set up the root logger to print to stdout with a consistent format.
    """
    # Create a logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Avoid adding duplicate handlers if this is called multiple times
    if logger.hasHandlers():
        logger.handlers.clear()

    # Create a handler for stdout
    handler = logging.StreamHandler(sys.stdout)

    # Create a formatter and set it for the handler
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler.setFormatter(formatter)

    # Add the handler to the logger
    logger.addHandler(handler)

    # Silence noisy third-party libraries
    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
"""
logger.py

Simple logging utility.
"""

from pathlib import Path
from datetime import datetime

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)


def write_log(browser_name, message):

    now = datetime.now()

    log_file = LOG_DIR / f"{now.strftime('%Y-%m-%d')}.log"

    with open(log_file, "a", encoding="utf-8") as file:

        file.write(
            f"[{now.strftime('%H:%M:%S')}] [{browser_name}] {message}\n"
        )
