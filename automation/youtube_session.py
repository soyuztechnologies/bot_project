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

import random
import logging
import queue
import time
import threading
from datetime import datetime
import uuid

from browser.browser import setup_browser, close_browser

from utils.database import create_automation_run, update_automation_run
from automation.youtube import (
    open_youtube,
    search_video,
    find_target_video,
    watch_video,
    go_to_home,
    close_mini_player,
)

_ACTIVE_DRIVERS = set()
_STATS_LOCK = threading.Lock() # Need a lock for stats if multiple threads update a shared stats object
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


def run_session(keyword, config, stop_event, stats):
    """
    Run one complete YouTube automation session for a single keyword.
    """

    driver = None
    run_id = uuid.uuid4() # Renamed from session_id to run_id
    thread_id = threading.get_ident()
    browser_mode = config["browser"]["mode"].capitalize()
    target_channel = config["youtube"]["targetChannel"]
    automation_type = "YOUTUBE"

    original_keyword = keyword
    current_search_keyword = original_keyword
    fallback_used = False

    # Initialize run-specific stats
    success_count = 0
    failure_count = 0
    retry_count = 0

    session_logger = logging.LoggerAdapter(
        logger,
        {
            "keyword": original_keyword, # Add keyword to logger context
            "engine": "youtube", # Use 'youtube' as the engine name for logs
            "search_keyword": current_search_keyword,
            "session_id": run_id, # Pass run_id as session_id for LoggerAdapter
            "app_module": automation_type,
            "website": "youtube.com",
            "target": target_channel,
            "thread_id": thread_id,
        },
    )

    # Create initial session record in the database
    create_automation_run(
        run_id=run_id,
        automation_type=automation_type,
        original_keyword=original_keyword,
        search_keyword=current_search_keyword,
        browser_mode=browser_mode,
        target=target_channel,
        search_engine="youtube"
    )

    try:

        if stop_event.is_set():
            return

        session_logger.info(f"Starting YouTube session for keyword: {original_keyword}", extra={'action': 'SESSION_STARTED', 'status': 'RUNNING'})

        driver = setup_browser(config)
        _register_driver(driver)

        if stop_event.is_set():
            return

        open_youtube(driver, config, stop_event, session_logger)

        if stop_event.is_set():
            return

        session_logger.info(f"Searching for keyword: {current_search_keyword}", extra={'action': 'KEYWORD_SEARCH', 'status': 'RUNNING'})

        success, _ = retry_operation(
            session_logger,
            lambda: search_video(driver, current_search_keyword, config, stop_event, session_logger),
            stop_event,
        )

        if not success:
            session_logger.error(f"Failed to search for keyword: {current_search_keyword}", extra={'action': 'KEYWORD_SEARCH', 'status': 'FAILED'})
            raise Exception(f"Failed to search for keyword: {current_search_keyword}")

        if stop_event.is_set():
            return

        success, found = retry_operation(
            session_logger,
            lambda: find_target_video(driver, config, stop_event, session_logger),
            stop_event,
        )

        if not success:
            session_logger.error("Failed while finding target video.", extra={'action': 'VIDEO_SEARCH', 'status': 'FAILED'})
            raise Exception("Failed while finding target video.")

        if not found:
            extra_keyword = config.get("youtube", {}).get("extra_keyword", "").strip()
            if extra_keyword and extra_keyword.lower() not in original_keyword.lower():
                fallback_used = True
                current_search_keyword = f"{original_keyword} {extra_keyword}"
                session_logger.extra['search_keyword'] = current_search_keyword

                session_logger.warning(
                    f"Video not found. Retrying with fallback keyword: '{current_search_keyword}'",
                    extra={'action': 'FALLBACK_SEARCH_STARTED', 'status': 'RUNNING'}
                )

                # Search again with the fallback keyword
                success, _ = retry_operation(
                    session_logger,
                    lambda: search_video(driver, current_search_keyword, config, stop_event, session_logger),
                    stop_event,
                )
                if not success:
                    session_logger.error(f"Failed to search for fallback keyword: {current_search_keyword}", extra={'action': 'KEYWORD_SEARCH', 'status': 'FAILED'})
                    raise Exception(f"Failed to search for fallback keyword: {current_search_keyword}")

                # Find video again
                success, found = retry_operation(
                    session_logger,
                    lambda: find_target_video(driver, config, stop_event, session_logger),
                    stop_event,
                )
                if not success:
                    session_logger.error("Failed while finding target video on fallback.", extra={'action': 'VIDEO_SEARCH', 'status': 'FAILED'})
                    raise Exception("Failed while finding target video on fallback.")

        if stop_event.is_set():
            return

        if found:
            session_logger.info("Target channel video found.", extra={'action': 'VIDEO_FOUND', 'status': 'SUCCESS'})
            watch_video(driver, config, stop_event, session_logger, keyword=current_search_keyword)
            if stop_event.is_set(): return
            go_to_home(driver, config, stop_event, session_logger)
            close_mini_player(driver, session_logger)
            with _STATS_LOCK:
                stats["success"].append({"keyword": original_keyword, "engine": "youtube"})
            success_count = 1
            status = "SUCCESS"
        else:
            session_logger.warning("Target channel video not found.", extra={'action': 'VIDEO_NOT_FOUND', 'status': 'FAILED'})
            with _STATS_LOCK:
                stats["failed"].append({"keyword": original_keyword, "engine": "youtube"})
            failure_count = 1
            status = "FAILED"

    except Exception as error:
        if not stop_event.is_set():
            with _STATS_LOCK:
                stats["failed"].append({"keyword": original_keyword, "engine": "youtube"})
            failure_count = 1
            status = "FAILED"
            session_logger.error(
                f"Session Error ({original_keyword} | YouTube)",
                exc_info=True,
                extra={'action': 'SESSION_ERROR', 'status': 'FAILED', 'error_message': str(error)}
            )

    finally:
        if driver:
            try:
                close_browser(driver)
            finally:
                _unregister_driver(driver)

        session_end_time = datetime.now()
        if 'status' not in locals():
            status = "FAILED" if failure_count > 0 else "COMPLETED"
        if stop_event.is_set():
            status = "INTERRUPTED"

        update_automation_run(
            run_id=run_id,
            finished_at=session_end_time,
            status=status,
            success_count=success_count,
            failure_count=failure_count,
            retry_count=retry_count,
            fallback_used=fallback_used,
            search_keyword=current_search_keyword
        )


def _session_worker(job_queue, config, stop_event, stats):
    """
    Worker thread that runs one browser session.
    """
    while not stop_event.is_set():
        keyword = None
        try:
            keyword = job_queue.get_nowait()
            run_session(keyword, config, stop_event, stats)
        except queue.Empty:
            return # No more jobs, worker can exit.
        except Exception as error:
            # This catches crashes within run_session (e.g., browser connection lost)
            logger.error(f"Unhandled error in session worker for keyword '{keyword}': {error}", exc_info=True)
            if keyword: # Ensure the failed keyword is tracked
                with _STATS_LOCK:
                    if not any(d.get('keyword') == keyword for d in stats['failed']):
                         stats["failed"].append({"keyword": keyword, "engine": "youtube"})
        finally:
            if keyword: # Ensure task_done is only called if a keyword was retrieved
                job_queue.task_done()


def start_parallel_sessions(keywords, config, stats):
    """
    Start multiple YouTube sessions in parallel.
    """
    max_workers = min(int(config["sessions"]["parallel"]), len(keywords))
    stop_event = threading.Event()
    job_queue = queue.Queue()

    # Shuffle keywords to randomize order
    random.shuffle(keywords)
    for keyword in keywords:
        job_queue.put(keyword)

    workers = []
    for _ in range(max_workers):
        workers.append(
            threading.Thread(
                target=_session_worker,
                args=(job_queue, config, stop_event, stats),
                daemon=True,
            )
        )

    try:
        for worker in workers:
            worker.start()
        # Block until all jobs are processed
        while job_queue.unfinished_tasks > 0:
            time.sleep(0.5)
    except KeyboardInterrupt:

        logger.info("\nCtrl+C detected. Stopping automation...")
        stop_event.set()
        # Re-raise the exception to allow the main loop to catch it and exit.
        raise

    finally:
        # This ensures cleanup happens whether jobs complete or are interrupted
        stop_event.set()
        close_active_drivers()
        for worker in workers:
            worker.join(timeout=2)
        if stop_event.is_set():
            logger.info("Automation stopped.")

    return stats
