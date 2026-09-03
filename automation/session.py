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
    retry_operation_search, # Import the new retry wrapper
)
from automation.website import visit_website
from utils.database import create_automation_run, update_automation_run

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


def _is_browser_alive(driver) -> bool:
    if not driver:
        return False
    try:
        _ = driver.current_url
        return True
    except Exception:
        return False


def _safe_create_run(*args, **kwargs):
    try:
        create_automation_run(*args, **kwargs)
    except Exception as e:
        logger.warning(f"DB create_automation_run failed (non-fatal): {e}", exc_info=False)


def _safe_update_run(*args, **kwargs):
    try:
        update_automation_run(*args, **kwargs)
    except Exception as e:
        logger.warning(f"DB update_automation_run failed (non-fatal): {e}", exc_info=False)


def _safe_driver_get(driver, url, session_logger=None, stop_event=None, timeout=30):
    """Best-effort driver.get with timeout handling."""
    if stop_event and stop_event.is_set():
        return False
    if not _is_browser_alive(driver):
        if session_logger:
            session_logger.warning("Browser not alive before driver.get", extra={'action': 'DRIVER_GET', 'status': 'FAILED'})
        return False
    try:
        driver.set_page_load_timeout(timeout)
    except Exception:
        pass
    try:
        driver.get(url)
        return True
    except Exception as e:
        if session_logger:
            session_logger.warning(f"driver.get failed for {url}: {e}", extra={'action': 'DRIVER_GET', 'status': 'FAILED', 'error_message': str(e), 'url': url})
        return False


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
    """Finds and navigates to internal links on the website. Best-effort, never fails session."""
    try:
        internal_links_config = config.get("website", {}).get("internal_links", {})

        if not internal_links_config.get("enabled"):
            return

        if stop_event.is_set():
            return
        if not _is_browser_alive(driver):
            session_logger.warning("Skipping internal links - browser not alive", extra={'action': 'INTERNAL_LINK_SEARCH', 'status': 'SKIPPED'})
            return

        session_logger.info("Searching for internal links to visit...", extra={'action': 'INTERNAL_LINK_SEARCH', 'status': 'RUNNING'})
        max_to_visit = internal_links_config.get("max_to_visit", 0)
        selectors = internal_links_config.get("selectors", [])
        target_domain = config["website"]["domain"]

        if max_to_visit <= 0 or not selectors or not target_domain:
            session_logger.info("Internal links disabled by config (max_to_visit/selectors/domain)", extra={'action': 'INTERNAL_LINK_SEARCH', 'status': 'SKIPPED'})
            return

        # Use a set to avoid duplicate URLs
        link_urls = set()
        for selector in selectors:
            if stop_event.is_set():
                return
            if not _is_browser_alive(driver):
                return
            try:
                elements = driver.find_elements(By.XPATH, selector)
                for element in elements:
                    try:
                        href = element.get_attribute("href")
                    except Exception:
                        continue
                    # Ensure the link is valid and internal
                    if href and target_domain in href:
                        link_urls.add(href)
            except Exception as e:
                session_logger.warning(
                    f"Error finding links with selector '{selector}': {e}",
                    extra={'action': 'INTERNAL_LINK_SEARCH', 'status': 'FAILED'}
                )
                continue

        if not link_urls:
            session_logger.info("No internal links found to visit.", extra={'action': 'INTERNAL_LINK_SEARCH', 'status': 'SUCCESS'})
            return

        # Get a random sample of links to visit
        try:
            links_to_visit = random.sample(list(link_urls), min(len(link_urls), max_to_visit))
        except Exception as e:
            session_logger.warning(f"Failed to sample internal links: {e}", extra={'action': 'INTERNAL_LINK_SEARCH', 'status': 'FAILED'})
            return

        session_logger.info(
            f"Found {len(links_to_visit)} internal link(s) to visit.",
            extra={'action': 'INTERNAL_LINK_SEARCH', 'status': 'SUCCESS'}
        )

        for url in links_to_visit:
            if stop_event.is_set():
                return
            if not _is_browser_alive(driver):
                session_logger.warning("Browser died during internal link visits", extra={'action': 'INTERNAL_LINK_VISIT', 'status': 'FAILED'})
                return
            try:
                session_logger.info(f"Visiting internal link: {url}", extra={'action': 'INTERNAL_LINK_VISIT', 'status': 'RUNNING', 'url': url})
                # Use safe get with timeout handling
                ok = _safe_driver_get(driver, url, session_logger, stop_event)
                if not ok:
                    session_logger.warning(f"Failed to navigate to internal link: {url}", extra={'action': 'INTERNAL_LINK_VISIT', 'status': 'FAILED', 'url': url})
                    continue
                # Simulate user reading the page
                min_sleep = config.get("timing", {}).get("sleepMin", 2)
                max_sleep = config.get("timing", {}).get("sleepMax", 4)
                try:
                    time.sleep(random.uniform(min_sleep, max_sleep))
                except Exception:
                    pass
                session_logger.info(f"Successfully visited internal link: {url}", extra={'action': 'INTERNAL_LINK_VISIT', 'status': 'SUCCESS', 'url': url})
            except Exception as e:
                session_logger.warning(f"Error visiting internal link {url}: {e} (continuing)", extra={'action': 'INTERNAL_LINK_VISIT', 'status': 'FAILED', 'url': url, 'error_message': str(e)})
                if not _is_browser_alive(driver):
                    return
                continue
    except Exception as e:
        # Outer catch - internal links must never kill session
        try:
            session_logger.warning(f"Internal links flow failed but session continues: {e}", extra={'action': 'INTERNAL_LINK_SEARCH', 'status': 'FAILED', 'error_message': str(e)})
        except Exception:
            pass


def run_session(keyword, config, engine_name, engine, stop_event, stats):
    driver = None
    run_id = uuid.uuid4()
    thread_id = threading.get_ident()
    browser_mode = str(config.get("browser", {}).get("mode", "headed")).capitalize()
    target = config.get("website", {}).get("domain", "")
    automation_type = "SEARCH"

    original_keyword = keyword
    current_search_keyword = original_keyword
    fallback_used = False
    status = None

    browser_list = config["browser"].get("browsers") or list(
        config["browser"].get("distribution", {}).keys()
    )
    selected_browser = (browser_list[0] if browser_list else "chrome").lower()

    # Create a LoggerAdapter that will add session-specific context to all logs.
    session_logger = logging.LoggerAdapter(
        logger,
        {
            "keyword": keyword,
            "engine": engine_name,
            "search_keyword": current_search_keyword,
            "session_id": run_id,
            "app_module": automation_type,
            "website": config.get("website", {}).get("domain"),
            "target": target,
            "thread_id": thread_id,
        },
    )

    # Initialize run-specific stats
    success_count = 0
    failure_count = 0
    retry_count = 0

    # Create initial session record in the database - never let DB failure kill session
    _safe_create_run(run_id, automation_type, original_keyword, current_search_keyword, browser_mode, target, engine_name)

    try:
        if stop_event.is_set():
            status = "INTERRUPTED"
            return

        session_logger.info(
            f"Starting session for: {original_keyword} [{engine_name}]",
            extra={'action': 'SESSION_STARTED', 'status': 'RUNNING'}
        )

        # -------------------------------------------------
        # 1) Browser startup - with isolated handling
        # -------------------------------------------------
        try:
            driver = setup_browser(config, selected_browser)
            _register_driver(driver)
            session_logger.info(f"Browser started: {selected_browser}", extra={'action': 'BROWSER_STARTED', 'status': 'SUCCESS'})
        except Exception as e:
            session_logger.error(f"Browser startup failed ({selected_browser}): {e}", exc_info=True, extra={'action': 'BROWSER_START_FAILED', 'status': 'FAILED', 'error_message': str(e)})
            with _STATS_LOCK:
                stats["failed"].append({"keyword": original_keyword, "engine": engine_name})
            failure_count = 1
            status = "FAILED"
            return

        if stop_event.is_set() or not _is_browser_alive(driver):
            status = "INTERRUPTED" if stop_event.is_set() else "FAILED"
            if not _is_browser_alive(driver):
                session_logger.warning("Browser died immediately after startup", extra={'action': 'BROWSER_HEALTH', 'status': 'FAILED'})
                with _STATS_LOCK:
                    # avoid duplicate
                    if not any(d.get('keyword') == original_keyword for d in stats["failed"]):
                        stats["failed"].append({"keyword": original_keyword, "engine": engine_name})
                failure_count = 1
                status = "FAILED"
            return

        # -------------------------------------------------
        # 2) Open search engine - best effort, fallback to direct URL if fails
        # -------------------------------------------------
        try:
            session_logger.info(f"Opening search engine: {engine_name}", extra={'action': 'ENGINE_OPEN', 'status': 'RUNNING'})
            open_search_engine(driver, engine, session_logger, stop_event)
            session_logger.info(f"Search engine opened: {engine_name}", extra={'action': 'ENGINE_OPEN', 'status': 'SUCCESS'})
        except Exception as e:
            session_logger.warning(f"Open search engine failed ({engine_name}): {e} - will try direct search fallback", exc_info=False, extra={'action': 'ENGINE_OPEN', 'status': 'FAILED', 'error_message': str(e)})
            # Don't return - search_keyword has direct URL fallback, so continue
            if not _is_browser_alive(driver):
                session_logger.error("Browser died during engine open", extra={'action': 'ENGINE_OPEN', 'status': 'FAILED'})
                with _STATS_LOCK:
                    if not any(d.get('keyword') == original_keyword for d in stats["failed"]):
                        stats["failed"].append({"keyword": original_keyword, "engine": engine_name})
                failure_count = 1
                status = "FAILED"
                return

        if stop_event.is_set():
            status = "INTERRUPTED"
            return
        if not _is_browser_alive(driver):
            session_logger.warning("Browser not alive before search", extra={'action': 'BROWSER_HEALTH', 'status': 'FAILED'})
            with _STATS_LOCK:
                if not any(d.get('keyword') == original_keyword for d in stats["failed"]):
                    stats["failed"].append({"keyword": original_keyword, "engine": engine_name})
            failure_count = 1
            status = "FAILED"
            return

        # -------------------------------------------------
        # 3) Search keyword - any failure here is session failure, but handled gracefully
        # -------------------------------------------------
        try:
            search_keyword(driver, engine, current_search_keyword, config, stop_event, session_logger)
        except Exception as e:
            session_logger.error(f"Search failed for '{current_search_keyword}' on {engine_name}: {e}", exc_info=True, extra={'action': 'KEYWORD_SEARCH', 'status': 'FAILED', 'error_message': str(e)})
            with _STATS_LOCK:
                if not any(d.get('keyword') == original_keyword for d in stats["failed"]):
                    stats["failed"].append({"keyword": original_keyword, "engine": engine_name})
            failure_count = 1
            status = "FAILED"
            return

        if stop_event.is_set():
            status = "INTERRUPTED"
            return
        if not _is_browser_alive(driver):
            session_logger.warning("Browser died after search", extra={'action': 'BROWSER_HEALTH', 'status': 'FAILED'})
            with _STATS_LOCK:
                if not any(d.get('keyword') == original_keyword for d in stats["failed"]):
                    stats["failed"].append({"keyword": original_keyword, "engine": engine_name})
            failure_count = 1
            status = "FAILED"
            return
        
        

        # -------------------------------------------------
        # 4) Find target website - with retry wrapper, already robust
        # -------------------------------------------------
        found = False
        try:
            found, retry_count = retry_operation_search(driver, engine, target, 20, stop_event, session_logger)
        except Exception as e:
            session_logger.error(f"Find target website crashed: {e}", exc_info=True, extra={'action': 'WEBSITE_SEARCH', 'status': 'FAILED', 'error_message': str(e)})
            found = False

        # -------------------------------------------------
        # 5) Fallback keyword if not found
        # -------------------------------------------------
        if not found:
            try:
                extra_keyword = config.get("website", {}).get("extra_keyword", "").strip()
                if extra_keyword and extra_keyword.lower() not in original_keyword.lower():
                    fallback_used = True
                    current_search_keyword = f"{original_keyword} {extra_keyword}"
                    try:
                        session_logger.extra['search_keyword'] = current_search_keyword
                    except Exception:
                        pass
                    session_logger.warning(f"Website not found. Retrying with fallback keyword: '{current_search_keyword}'", extra={'action': 'FALLBACK_SEARCH_STARTED', 'status': 'RUNNING'})
                    if not _is_browser_alive(driver):
                        session_logger.warning("Browser died before fallback search", extra={'action': 'FALLBACK_SEARCH_STARTED', 'status': 'FAILED'})
                    else:
                        # Fallback search - isolated
                        try:
                            search_keyword(driver, engine, current_search_keyword, config, stop_event, session_logger)
                        except Exception as e:
                            session_logger.warning(f"Fallback search failed: {e}", extra={'action': 'FALLBACK_SEARCH_STARTED', 'status': 'FAILED', 'error_message': str(e)})
                            found = False
                        else:
                            if stop_event.is_set():
                                status = "INTERRUPTED"
                                return
                            try:
                                found, fallback_retry_count = retry_operation_search(driver, engine, target, config["search"].get("maxPages", 20), stop_event, session_logger)
                                retry_count += fallback_retry_count
                            except Exception as e:
                                session_logger.warning(f"Fallback find failed: {e}", extra={'action': 'WEBSITE_SEARCH', 'status': 'FAILED', 'error_message': str(e)})
                                found = False
            except Exception as e:
                session_logger.warning(f"Fallback flow failed but continuing: {e}", extra={'action': 'FALLBACK_SEARCH_STARTED', 'status': 'FAILED', 'error_message': str(e)})

        if stop_event.is_set():
            status = "INTERRUPTED"
            return

        # -------------------------------------------------
        # 6) Result handling - website found vs not found
        # -------------------------------------------------
        if found:
            try:
                cur_url = driver.current_url if _is_browser_alive(driver) else ""
            except Exception:
                cur_url = ""
            session_logger.info(f"Website found for '{current_search_keyword}' on {engine_name}.", extra={'action': 'WEBSITE_FOUND', 'status': 'SUCCESS', 'url': cur_url})
            # Visit website - best effort, must not fail session
            try:
                visit_website(driver, config, stop_event, session_logger)
            except Exception as e:
                session_logger.warning(f"visit_website best-effort failed: {e}", extra={'action': 'WEBSITE_VISIT', 'status': 'FAILED', 'error_message': str(e)})
            # Internal links - best effort
            try:
                _click_internal_links(driver, config, stop_event, session_logger)
            except Exception as e:
                session_logger.warning(f"Internal links best-effort failed: {e}", extra={'action': 'INTERNAL_LINK_SEARCH', 'status': 'FAILED', 'error_message': str(e)})
            with _STATS_LOCK:
                stats["success"].append({"keyword": original_keyword, "engine": engine_name})
            success_count = 1
            status = "SUCCESS"
        else:
            session_logger.warning(f"Website not found for '{current_search_keyword}' on {engine_name}.", extra={'action': 'WEBSITE_NOT_FOUND', 'status': 'FAILED'})
            failure_count = 1
            status = "FAILED"
            with _STATS_LOCK:
                if not any(d.get('keyword') == original_keyword for d in stats["failed"]):
                    stats["failed"].append({"keyword": original_keyword, "engine": engine_name})

    except Exception as error:
        # Global safety net - any unhandled exception
        if not stop_event.is_set():
            try:
                with _STATS_LOCK:
                    if not any(d.get('keyword') == original_keyword for d in stats["failed"]):
                        stats["failed"].append({"keyword": original_keyword, "engine": engine_name})
            except Exception:
                pass
            failure_count = 1
            status = "FAILED"
            try:
                session_logger.error(f"Session Error ({original_keyword} | {engine_name})", exc_info=True, extra={'action': 'SESSION_ERROR', 'status': 'FAILED', 'error_message': str(error)})
            except Exception:
                logger.error(f"Session Error ({original_keyword} | {engine_name}): {error}", exc_info=True)
        else:
            status = "INTERRUPTED"
    finally:
        # Always cleanup driver
        if driver:
            try:
                _unregister_driver(driver)
            except Exception:
                pass
            try:
                close_browser(driver)
            except Exception as e:
                try:
                    session_logger.warning(f"Browser close failed: {e}", extra={'action': 'BROWSER_CLOSE', 'status': 'FAILED', 'error_message': str(e)})
                except Exception:
                    logger.warning(f"Browser close failed: {e}")

        session_end_time = datetime.now()
        if status is None:
            status = "FAILED" if failure_count > 0 else "COMPLETED"
        if stop_event.is_set():
            status = "INTERRUPTED"

        _safe_update_run(run_id, session_end_time, status, success_count, failure_count, retry_count, fallback_used=fallback_used, search_keyword=current_search_keyword)


def _session_worker(job_queue, config, stop_event, stats):
    while not stop_event.is_set():
        job = None
        try:
            try:
                job = job_queue.get_nowait()
            except queue.Empty:
                return
            keyword, engine_name, engine = job
            try:
                run_session(keyword, config, engine_name, engine, stop_event, stats)
            except Exception as error:
                # Isolated - one keyword failure must not kill worker or other jobs
                logger.error(f"Unhandled error in session worker for '{keyword}' [{engine_name}]: {error}", exc_info=True)
                try:
                    with _STATS_LOCK:
                        if not any(d.get('keyword') == keyword for d in stats.get("failed", [])):
                            stats["failed"].append({"keyword": keyword, "engine": engine_name})
                except Exception:
                    pass
        except Exception as e:
            # Queue-level safety
            logger.error(f"Worker loop error: {e}", exc_info=True)
        finally:
            # Always mark task done if we took a job
            if job is not None:
                try:
                    job_queue.task_done()
                except Exception:
                    pass
            # Small yield to avoid tight loop when queue empty
            if job is None:
                time.sleep(0.1)


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
    Robust: isolated job failures never stop other jobs; browsers always cleaned up.
    """
    if not keywords:
        logger.warning("No keywords to process", extra={'action': 'SESSION_START', 'status': 'SKIPPED'})
        return {"total": 0, "success": [], "failed": []}
    if not engine_names:
        logger.error("No search engines configured", extra={'action': 'SESSION_START', 'status': 'FAILED'})
        return {"total": 0, "success": [], "failed": []}

    try:
        jobs = _build_jobs(keywords, search_engines, engine_names)
    except Exception as e:
        logger.error(f"Failed to build jobs: {e}", exc_info=True)
        return {"total": 0, "success": [], "failed": []}

    stats = {
        "total": len(jobs),
        "success": [],
        "failed": [],
    }

    # Cap workers to avoid idle threads, but ensure at least 1 if jobs exist
    try:
        requested = int(config["sessions"].get("parallel", 1))
    except Exception:
        requested = 1
    max_workers = max(1, min(requested, len(jobs))) if jobs else 0

    if max_workers == 0:
        return stats

    logger.info(f"Starting {len(jobs)} job(s) with {max_workers} worker(s) | Engines: {', '.join(engine_names)}", extra={'action': 'SESSION_START', 'status': 'RUNNING'})

    stop_event = threading.Event()
    job_queue = queue.Queue()

    for job in jobs:
        job_queue.put(job)

    workers = []
    for i in range(max_workers):
        try:
            w = threading.Thread(target=_session_worker, args=(job_queue, config, stop_event, stats), daemon=True, name=f"Worker-{i+1}")
            workers.append(w)
        except Exception as e:
            logger.error(f"Failed to create worker {i}: {e}")

    for w in workers:
        try:
            w.start()
        except Exception as e:
            logger.error(f"Failed to start worker {w.name}: {e}", exc_info=True)

    try:
        # Block until all jobs are processed, checking browser health periodically
        while job_queue.unfinished_tasks > 0:
            if stop_event.is_set():
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        logger.info("\nCtrl+C detected. Stopping all browser sessions...", extra={'action': 'SESSION_INTERRUPT', 'status': 'RUNNING'})
        stop_event.set()
        raise
    except Exception as e:
        logger.error(f"Unexpected error in parallel runner: {e}", exc_info=True)
        stop_event.set()
    finally:
        # Ensure cleanup happens whether jobs complete or are interrupted
        stop_event.set()
        try:
            close_active_drivers()
        except Exception as e:
            logger.warning(f"close_active_drivers failed: {e}")
        for w in workers:
            try:
                w.join(timeout=5)
                if w.is_alive():
                    logger.warning(f"Worker {w.name} did not exit cleanly")
            except Exception as e:
                logger.warning(f"Worker join failed for {w.name}: {e}")
        # Final summary log
        try:
            logger.info(f"Parallel run finished: total={stats['total']} success={len(stats['success'])} failed={len(stats['failed'])}", extra={'action': 'SESSION_FINISHED', 'status': 'SUCCESS' if not stats['failed'] else 'COMPLETED'})
        except Exception:
            pass

    return stats