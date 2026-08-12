"""
youtube_session.py

This module manages YouTube automation sessions.

Responsibilities:
1. Start browser.
2. Open YouTube.
3. Search keyword.
4. Find target channel video.
5. Watch video.
6. Run multiple sessions in parallel.
7. Stop running sessions cleanly on Ctrl+C.
"""

import logging
import queue
import threading
from datetime import datetime
import uuid

from browser.browser import setup_browser, close_browser

from utils.database import create_session_record, update_session_record
from automation.youtube import (
    open_youtube,
    search_video,
    find_target_video,
    watch_video,
    go_to_home,
    close_mini_player,
)

_ACTIVE_DRIVERS = set()
_ACTIVE_DRIVERS_LOCK = threading.Lock()
logger = logging.getLogger(__name__)


def _register_driver(driver):
    with _ACTIVE_DRIVERS_LOCK:
        _ACTIVE_DRIVERS.add(driver)


def _unregister_driver(driver):
    with _ACTIVE_DRIVERS_LOCK:
        _ACTIVE_DRIVERS.discard(driver)


def close_active_drivers():
    """Close every browser that is currently running."""

    with _ACTIVE_DRIVERS_LOCK:
        drivers = list(_ACTIVE_DRIVERS)

    for driver in drivers:
        close_browser(driver)


def retry_operation(session_logger, operation, stop_event, retries=3, delay=3):
    """
    Retry an operation before giving up.
    """

    for attempt in range(1, retries + 1):

        try:
            result = operation()

            # Success
            return True, result

        except Exception as error:
            session_logger.warning(
                f"Operation failed on attempt {attempt}/{retries}",
                exc_info=True,
                extra={'action': 'RETRY_OPERATION', 'status': 'FAILED', 'error_message': str(error)}
            )
            if attempt < retries:
                if stop_event.is_set(): return False, None
                stop_event.wait(delay)
    return False, None


def run_session(keywords, config, stop_event):
    """
    Run one complete YouTube automation session.
    """

    driver = None
    session_id = uuid.uuid4()
    thread_id = threading.get_ident()
    browser_mode = config["browser"]["mode"].capitalize()
    target_website_domain = "youtube.com" # Fixed for YouTube
    session_start_time = datetime.now()

    session_id = uuid.uuid4()
    session_logger = logging.LoggerAdapter(
        logger,
        {
            "session_id": session_id,
            "app_module": "YOUTUBE",
            "website": "youtube.com",
            "target_website": target_website_domain,
            "thread_id": thread_id,
        },
    )

    try:

        if stop_event.is_set():
            return

        session_logger.info("Starting YouTube session")
        # Create initial session record in the database
        create_session_record(session_id, "YOUTUBE", thread_id, browser_mode, target_website_domain)

        session_logger.info("Starting YouTube session", extra={'action': 'SESSION_STARTED', 'status': 'RUNNING'})

        driver = setup_browser(config)
        _register_driver(driver)

        if stop_event.is_set():
            return

        open_youtube(driver, config, stop_event, session_logger)

        if stop_event.is_set():
            return

        session_stats = {
            "total_keywords": len(keywords),
            "successful_keywords": 0,
            "failed_keywords": 0,
        }

        for keyword in keywords:
            if stop_event.is_set():
                return

            # Add keyword to the logger's context for this loop
            session_logger.extra['keyword'] = keyword

            session_logger.info(f"Searching for keyword: {keyword}", extra={'action': 'KEYWORD_SEARCH', 'status': 'RUNNING'})

            success, _ = retry_operation(
                session_logger,
                lambda: search_video(driver, keyword, config, stop_event, session_logger),
                stop_event,
            )

            if not success:
                session_logger.error(f"Failed to search for keyword: {keyword}", extra={'action': 'KEYWORD_SEARCH', 'status': 'FAILED'})
                session_stats["failed_keywords"] += 1
                continue

            if stop_event.is_set():
                return

            success, found = retry_operation(
                session_logger,
                lambda: find_target_video(driver, config, stop_event, session_logger),
                stop_event,
            )

            if not success:
                session_logger.error("Failed while finding target video.", extra={'action': 'VIDEO_SEARCH', 'status': 'FAILED'})
                continue

            if stop_event.is_set():
                return

            if found:
                session_logger.info("Target channel video found.", extra={'action': 'VIDEO_FOUND', 'status': 'SUCCESS'})
                watch_video(driver, config, stop_event, session_logger, keyword=keyword)
                if stop_event.is_set(): return
                go_to_home(driver, config, stop_event, session_logger)
                close_mini_player(driver, session_logger)
                session_stats["successful_keywords"] += 1
            else:
                session_logger.warning("Target channel video not found.", extra={'action': 'VIDEO_NOT_FOUND', 'status': 'FAILED'})
                session_stats["failed_keywords"] += 1

    except Exception as error:
        if not stop_event.is_set():
            session_logger.error(
                "YouTube Session Error",
                exc_info=True,
            )

    finally:
        if driver:
            try:
                close_browser(driver)
            finally:
                _unregister_driver(driver)

        session_end_time = datetime.now()
        session_status = "COMPLETED"
        if stop_event.is_set():
            session_status = "INTERRUPTED"

        update_session_record(
            session_id,
            session_end_time,
            session_status,
            session_stats.get("total_keywords", 0),
            session_stats.get("successful_keywords", 0),
            session_stats.get("failed_keywords", 0)
        )


def _session_worker(keywords, config, stop_event):
    """
    Worker thread that runs one browser session.
    """
    run_session(keywords, config, stop_event)


def start_parallel_sessions(keywords, config):
    """
    Start multiple YouTube sessions in parallel.
    """

    max_workers = int(config["sessions"]["parallel"])

    stop_event = threading.Event()

    workers = []

    for i in range(max_workers):

        workers.append(
            threading.Thread(
                target=_session_worker,
                args=(
                    keywords,
                    config,
                    stop_event,
                ),
                daemon=True,
                name=f"Thread-{i + 1}",
            )
        )

    try:

        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
    except KeyboardInterrupt:

        logger.info("\nCtrl+C detected. Stopping automation...")

        stop_event.set()

    finally:
        # This ensures cleanup happens whether jobs complete or are interrupted
        stop_event.set()
        close_active_drivers()
        for worker in workers:
            worker.join(timeout=2)
        if stop_event.is_set():
            logger.info("Automation stopped.")
