"""
website.py

Actions to perform after the target website has been opened from search
results.
"""

from utils.helpers import random_sleep, simulate_human_reading


def _is_browser_alive(driver) -> bool:
    if not driver:
        return False
    try:
        _ = driver.current_url
        return True
    except Exception:
        return False


def visit_website(driver, config: dict, stop_event=None, session_logger=None) -> None:
    """
    Simulate a short, human-like visit on the target website.
    Best-effort: any failure is logged and ignored so the session
    can still be marked SUCCESS (website was found).
    """
    if stop_event and stop_event.is_set():
        return
    if not _is_browser_alive(driver):
        if session_logger:
            session_logger.warning("Skipping website visit - browser not alive", extra={'action': 'WEBSITE_VISIT', 'status': 'SKIPPED'})
        return
    try:
        timing = config.get("timing", {})
        sleep_min = timing.get("sleepMin", 2)
        sleep_max = timing.get("sleepMax", 4)
        scroll_min = timing.get("scrollMin", 2)
        scroll_max = timing.get("scrollMax", 5)

        random_sleep(sleep_min, sleep_max, stop_event)

        for _ in range(2):
            if stop_event and stop_event.is_set():
                return
            try:
                simulate_human_reading(driver, stop_event)
            except Exception as e:
                if session_logger:
                    session_logger.warning(f"Human reading simulation failed: {e}", extra={'action': 'WEBSITE_VISIT', 'status': 'FAILED', 'error_message': str(e)})
                # best-effort, continue
                if not _is_browser_alive(driver):
                    return

        random_sleep(scroll_min, scroll_max, stop_event)
        if session_logger:
            session_logger.info("Website visit completed", extra={'action': 'WEBSITE_VISIT', 'status': 'SUCCESS'})
    except Exception as e:
        # Never let visit fail the whole session - website was already found
        if session_logger:
            session_logger.warning(f"Website visit failed but session will continue: {e}", extra={'action': 'WEBSITE_VISIT', 'status': 'FAILED', 'error_message': str(e)})
        else:
            print(f"[WEBSITE] Visit failed (best-effort): {e}")
