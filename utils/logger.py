import logging
import sys
import json
from pathlib import Path
from datetime import datetime


def _enable_logger_adapter_extra_merge():
    """Preserve per-log extra fields while keeping session context."""
    if getattr(logging.LoggerAdapter, "_seo_bot_merges_extra", False):
        return

    def process(self, msg, kwargs):
        adapter_extra = self.extra or {}
        call_extra = kwargs.get("extra") or {}
        kwargs["extra"] = {**adapter_extra, **call_extra}
        return msg, kwargs

    logging.LoggerAdapter.process = process
    logging.LoggerAdapter._seo_bot_merges_extra = True



class _NoisyConnectionFilter(logging.Filter):
    """Drop urllib3 retry / connection-refused spam that floods console on Ctrl+C."""
    _BLOCKED_SUBSTRINGS = (
        "NewConnectionError",
        "ConnectionResetError",
        "Connection pool is full",
        "Retrying (Retry",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        # Only filter third-party retry noise — keep our own app warnings
        if record.name.startswith("urllib3") or record.name.startswith("selenium"):
            for substr in self._BLOCKED_SUBSTRINGS:
                if substr in msg:
                    return False
        return True


_NOISY_FILTER = _NoisyConnectionFilter()


def silence_noisy_loggers():
    """Immediately silence urllib3/selenium retries — call on Ctrl+C before closing browsers."""
    for name in (
        "urllib3",
        "urllib3.connectionpool",
        "selenium",
        "selenium.webdriver.remote.remote_connection",
    ):
        lg = logging.getLogger(name)
        lg.setLevel(logging.ERROR)
        # Ensure filter is attached (idempotent)
        if _NOISY_FILTER not in lg.filters:
            lg.addFilter(_NOISY_FILTER)
    # Also filter root handlers so any propagated retry record is still dropped
    root = logging.getLogger()
    for h in root.handlers:
        if _NOISY_FILTER not in h.filters:
            h.addFilter(_NOISY_FILTER)


def setup_logger():
    """
    Set up the root logger to print to stdout with a consistent format.
    """
    _enable_logger_adapter_extra_merge()

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
    # Filter noisy retry messages even before explicit silence
    handler.addFilter(_NOISY_FILTER)

    # Add the handler to the logger
    logger.addHandler(handler)

    # Silence noisy third-party libraries — use ERROR to hide WARNING-level
    # retry spam (NewConnectionError / ConnectionResetError) that floods
    # console after Ctrl+C when drivers are quit.
    for name in (
        "urllib3",
        "urllib3.connectionpool",
        "selenium",
        "selenium.webdriver.remote.remote_connection",
    ):
        lg = logging.getLogger(name)
        lg.setLevel(logging.ERROR)
        if _NOISY_FILTER not in lg.filters:
            lg.addFilter(_NOISY_FILTER)



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
