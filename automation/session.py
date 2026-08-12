"""
session.py

This module manages automation sessions.

Responsibilities:
1. Start browser.
2. Open search engine.
3. Search keyword.
4. Visit website.
5. Close browser.
6. Run multiple sessions in parallel.
7. Stop running sessions cleanly on Ctrl+C.
"""
import logging
import queue
import sys
import threading
import uuid
import random
import time

from datetime import datetime
from selenium.webdriver.common.by import By

from browser.browser import setup_browser, close_browser
from automation.search_engine import (
    open_search_engine,
    search_keyword,
    find_target_website,
)
from automation.website import visit_website
from utils.database import create_session_record, update_session_record

# Backwards-compatibility fix for LoggerAdapter.
# In Python < 3.8, LoggerAdapter overwrites the 'extra' dictionary passed to
# logging calls. This monkey-patch ensures it merges the adapter's context with
# the call's 'extra' dict, which is the standard behavior in modern Python.
if sys.version_info < (3, 8):
    def _process_patched(self, msg, kwargs):
        """A patched version of LoggerAdapter.process to merge 'extra' dicts."""
        kwargs.setdefault('extra', {})
        # This loop adds the adapter's context to the 'extra' dict.
        for k, v in self.extra.items():
            kwargs['extra'][k] = v
        return msg, kwargs
    logging.LoggerAdapter.process = _process_patched

logger = logging.getLogger(__name__)

_ACTIVE_DRIVERS = set()
_ACTIVE_DRIVERS_LOCK = threading.Lock()
_STATS_LOCK = threading.Lock()


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


def _click_internal_links(driver, config, stop_event, session_logger):
    """Finds and navigates to internal links on the website."""
    internal_links_config = config.get("website", {}).get("internal_links", {})

    if not internal_links_config.get("enabled"):
        return

    if stop_event.is_set():
        return

    session_logger.info("Searching for internal links to visit...", extra={'action': 'INTERNAL_LINK_SEARCH', 'status': 'RUNNING'})
    max_to_visit = internal_links_config.get("max_to_visit", 0)
    selectors = internal_links_config.get("selectors", [])
    target_domain = config["website"]["domain"]

    if max_to_visit <= 0 or not selectors or not target_domain:
        return

    # Use a set to avoid duplicate URLs
    link_urls = set()
    for selector in selectors:
        if stop_event.is_set():
            return
        try:
            elements = driver.find_elements(By.XPATH, selector)
            for element in elements:
                href = element.get_attribute("href")
                # Ensure the link is valid and internal
                if href and target_domain in href:
                    link_urls.add(href)
        except Exception as e:
            session_logger.warning(
                f"Error finding links with selector '{selector}': {e}",
                extra={'action': 'INTERNAL_LINK_SEARCH', 'status': 'FAILED'}
            )

    if not link_urls:
        session_logger.info("No internal links found to visit.", extra={'action': 'INTERNAL_LINK_SEARCH', 'status': 'SUCCESS'})
        return

    # Get a random sample of links to visit
    links_to_visit = random.sample(list(link_urls), min(len(link_urls), max_to_visit))

    session_logger.info(
        f"Found {len(links_to_visit)} internal link(s) to visit.",
    )

    for url in links_to_visit:
        if stop_event.is_set():
            return

        try:
            session_logger.info(f"Visiting internal link: {url}", extra={'action': 'INTERNAL_LINK_VISIT', 'status': 'RUNNING', 'url': url})
            driver.get(url)
            # Simulate user reading the page
            min_sleep = config["timing"]["sleepMin"]
            max_sleep = config["timing"]["sleepMax"]
            time.sleep(random.uniform(min_sleep, max_sleep))
            session_logger.info(f"Successfully visited internal link: {url}", extra={'action': 'INTERNAL_LINK_VISIT', 'status': 'SUCCESS', 'url': url})
        except Exception as e:
            session_logger.error(f"Error visiting internal link {url}: {e}", extra={'action': 'INTERNAL_LINK_VISIT', 'status': 'FAILED', 'url': url, 'error_message': str(e)})


def run_session(keyword, config, engine_name, engine, stop_event, stats, session_stats):
    driver = None
    session_id = uuid.uuid4()
    thread_id = threading.get_ident()
    browser_mode = config["browser"]["mode"].capitalize()
    target_website_domain = config.get("website", {}).get("domain")
    session_start_time = datetime.now()

    # Create a LoggerAdapter that will add session-specific context to all logs.
    driver = None
    session_logger = logging.LoggerAdapter(
        logger,
        {
            "keyword": keyword,
            "engine": engine_name,
            "session_id": session_id,
            "app_module": "SEARCH",
            "website": config.get("website", {}).get("domain"),
            "target_website": target_website_domain,
            "thread_id": thread_id,
        },
    )

    # Create initial session record in the database
    create_session_record(session_id, "SEARCH", thread_id, browser_mode, target_website_domain)

    try:
        if stop_event.is_set():
            return

        session_logger.info(
            f"Starting session for: {keyword} [{engine_name}]",
            extra={'action': 'SESSION_STARTED', 'status': 'RUNNING'}
        )

        driver = setup_browser(config)
        _register_driver(driver)

        if stop_event.is_set():
            return

        if "searchUrl" not in engine:
            session_logger.info(
            f"Opening search engine: {engine_name}",
            extra={'action': 'ENGINE_OPEN', 'status': 'RUNNING'}
            )
            open_search_engine(driver, engine)

        if stop_event.is_set():
            return

        search_keyword(driver, engine, keyword, config, stop_event, session_logger)

        if stop_event.is_set():
            return

        found = find_target_website(
            driver,
            engine,
            target_website_domain,
            config["search"]["maxPages"],
            stop_event,
            session_logger, # Pass session_logger to find_target_website
        )

        if stop_event.is_set():
            return

        if found:
            session_logger.info(
                f"Website found for '{keyword}' on {engine_name}.",
                extra={'action': 'WEBSITE_FOUND', 'status': 'SUCCESS', 'url': driver.current_url}
            )

            visit_website(driver, config, stop_event)
            _click_internal_links(driver, config, stop_event, session_logger)

            with _STATS_LOCK:
                stats["success"].append({"keyword": keyword, "engine": engine_name})
            session_stats["success_count"] += 1

        else:
            session_logger.warning(
                f"Website not found for '{keyword}' on {engine_name}.",
                extra={'action': 'WEBSITE_NOT_FOUND', 'status': 'FAILED'}
            )
            session_stats["failed_count"] += 1

            with _STATS_LOCK:
                stats["failed"].append({"keyword": keyword, "engine": engine_name})

    except Exception as error:
            if not stop_event.is_set():
                
                with _STATS_LOCK:
                    stats["failed"].append({"keyword": keyword, "engine": engine_name})
                session_stats["failed_count"] += 1 # Mark as failed due to exception

                session_logger.error(
                    f"Session Error ({keyword} | {engine_name})",
                    exc_info=True,
                    extra={'action': 'SESSION_ERROR', 'status': 'FAILED', 'error_message': str(error)}
                )

    finally:
        if driver:
            _unregister_driver(driver)
            close_browser(driver)

        session_end_time = datetime.now()
        session_status = "COMPLETED" if session_stats["failed_count"] == 0 else "FAILED"
        if stop_event.is_set():
            session_status = "INTERRUPTED"

        update_session_record(
            session_id,
            session_end_time,
            session_status,
            session_stats["total_count"],
            session_stats["success_count"],
            session_stats["failed_count"]
        )


def _session_worker(job_queue, config, stop_event, stats):
    while not stop_event.is_set():
        try:
            keyword, engine_name, engine = job_queue.get_nowait()
            # Each session worker manages its own stats for the session_id
            session_stats = {
                "total_count": 1, # Each job is one keyword attempt
                "success_count": 0,
                "failed_count": 0}
            run_session(keyword, config, engine_name, engine, stop_event, stats, session_stats)
        except queue.Empty:
            return

        try:
            pass # The work is done in the try block above, this is for the exception.
        except Exception as error:
            logger.error(f"Unhandled error in session worker: {error}", exc_info=True)
        finally:
            job_queue.task_done()


def _build_jobs(keywords, search_engines, engine_names):
    jobs = []
 
    for keyword in keywords:
        # Assign a random search engine to each keyword for less predictable behavior.
        engine_name = random.choice(engine_names)
        jobs.append((keyword, engine_name, search_engines[engine_name]))
 
    # Shuffle the jobs to further randomize the order of execution across workers.
    random.shuffle(jobs)
    return jobs


def start_parallel_sessions(keywords, config, search_engines, engine_names):
    """
    Start multiple sessions in parallel.

    Args:
        keywords (list): List of keywords.
        config (dict): Project configuration.
        search_engines (dict): All search engine configurations.
        engine_names (list): Search engines to rotate across sessions.

    Returns:
        bool: True when all sessions complete, False when stopped.
    """
    jobs = _build_jobs(keywords, search_engines, engine_names)

    stats = {
        "total": len(jobs),
        "success": [],
        "failed": [],
    }
    max_workers = min(int(config["sessions"]["parallel"]), len(keywords))
    stop_event = threading.Event()
    job_queue = queue.Queue()

    for job in jobs:
        job_queue.put(job)

    workers = [
    threading.Thread(
        target=_session_worker,
        args=(job_queue, config, stop_event, stats),
        daemon=True,
    )
    for _ in range(max_workers)
    ]

    for worker in workers:
        worker.start()

    try:
        # Block until all jobs are processed
        # Use a loop with a sleep to make it interruptible by Ctrl+C
        while job_queue.unfinished_tasks > 0:
            time.sleep(0.5)
    except KeyboardInterrupt:
        logger.info("\nCtrl+C detected. Stopping all browser sessions...")
        stop_event.set()

    finally:
        # This ensures cleanup happens whether jobs complete or are interrupted
        stop_event.set()
        close_active_drivers()
        for worker in workers:
            worker.join(timeout=2)
        if stop_event.is_set():
            logger.info("Automation stopped.")

    return stats
