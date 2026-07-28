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

import queue
import threading

from browser.browser import setup_browser, close_browser
from automation.search_engine import (
    open_search_engine,
    search_keyword,
    find_target_website,
)
from automation.website import visit_website

_ACTIVE_DRIVERS = set()
_ACTIVE_DRIVERS_LOCK = threading.Lock()


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


def run_session(keyword, config, engine_name, engine, stop_event):
    """
    Run one complete automation session.

    Args:
        keyword (str): Search keyword.
        config (dict): Project configuration.
        engine_name (str): Search engine name.
        engine (dict): Search engine configuration.
        stop_event: Shared threading.Event used to stop work.
    """

    driver = None

    try:
        if stop_event.is_set():
            return

        print(f"Starting session for: {keyword} [{engine_name}]")

        driver = setup_browser(config)
        _register_driver(driver)

        if stop_event.is_set():
            return

        if "searchUrl" not in engine:
            open_search_engine(driver, engine)

        if stop_event.is_set():
            return

        search_keyword(driver, engine, keyword, config, stop_event)

        if stop_event.is_set():
            return

        found = find_target_website(
            driver,
            engine,
            config["website"]["domain"],
            config["search"]["maxPages"],
            stop_event,
        )

        if stop_event.is_set():
            return

        if found:
            print(f"Website found. [{engine_name}]")
            visit_website(driver, config, stop_event)
        else:
            print(f"Website not found. [{engine_name}]")

    except Exception as error:
        if not stop_event.is_set():
            print(f"Session Error ({keyword} | {engine_name}): {error}")

    finally:
        if driver:
            _unregister_driver(driver)
            close_browser(driver)


def _session_worker(job_queue, config, stop_event):
    while not stop_event.is_set():
        try:
            keyword, engine_name, engine = job_queue.get_nowait()
        except queue.Empty:
            return

        try:
            run_session(keyword, config, engine_name, engine, stop_event)
        finally:
            job_queue.task_done()


def _build_jobs(keywords, search_engines, engine_names):
    jobs = []

    for index, keyword in enumerate(keywords):
        engine_name = engine_names[index % len(engine_names)]
        jobs.append((keyword, engine_name, search_engines[engine_name]))

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

    max_workers = min(int(config["sessions"]["parallel"]), len(keywords))
    stop_event = threading.Event()
    job_queue = queue.Queue()

    for job in _build_jobs(keywords, search_engines, engine_names):
        job_queue.put(job)

    workers = [
        threading.Thread(
            target=_session_worker, args=(job_queue, config, stop_event), daemon=True
        )
        for _ in range(max_workers)
    ]

    try:
        for worker in workers:
            worker.start()

        while any(worker.is_alive() for worker in workers):
            for worker in workers:
                worker.join(timeout=0.2)

        return not stop_event.is_set()

    except KeyboardInterrupt:
        print("\nCtrl+C detected. Stopping all browser sessions...")
        stop_event.set()

        while True:
            try:
                job_queue.get_nowait()
                job_queue.task_done()
            except queue.Empty:
                break

        close_active_drivers()

        for worker in workers:
            worker.join(timeout=2)

        print("Automation stopped.")
        return False
