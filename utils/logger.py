import logging
import sys
import json
from pathlib import Path
from datetime import datetime



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



LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)


def fallback_log(event_data: dict):
    """
    Fallback logger that writes event data as a JSON line to a file
    when the database is unavailable.
    """
    now = datetime.now()
    log_file = LOG_DIR / f"fallback_{now.strftime('%Y-%m-%d')}.json.log"

    # Ensure timestamp is a string for JSON serialization
    event_with_timestamp = event_data.copy()
    if 'timestamp' not in event_with_timestamp:
        event_with_timestamp['timestamp'] = now.isoformat()

    try:
        # Convert non-serializable types to strings
        for key, value in event_with_timestamp.items():
            if not isinstance(value, (str, int, float, bool, list, dict, type(None))):
                event_with_timestamp[key] = str(value)
        with open(log_file, "a", encoding="utf-8") as file:
            file.write(json.dumps(event_with_timestamp) + "\n")
    except Exception as e:
        # If file logging also fails, print to stderr as a last resort.
        logging.critical(f"Fallback file logger failed: {e}")
        logging.critical(f"Original event data: {event_with_timestamp}")


def write_log(browser_name, message):

    now = datetime.now()

    log_file = LOG_DIR / f"{now.strftime('%Y-%m-%d')}.log"

    with open(log_file, "a", encoding="utf-8") as file:

        file.write(
            f"[{now.strftime('%H:%M:%S')}] [{browser_name}] {message}\n"
        )
