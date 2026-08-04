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