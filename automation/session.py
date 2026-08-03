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
import random
import time

from selenium.webdriver.common.by import By

from browser.browser import setup_browser, close_browser
from automation.search_engine import (
    open_search_engine,
    search_keyword,
    find_target_website,
)
from automation.website import visit_website

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


def _click_internal_links(driver, config, stop_event):
    """Finds and navigates to internal links on the website."""
    internal_links_config = config.get("website", {}).get("internal_links", {})

    if not internal_links_config.get("enabled"):
        return

    if stop_event.is_set():
        return

    print("Searching for internal links to visit...")

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
            print(f"Warning: Error finding links with selector '{selector}': {e}")

    if not link_urls:
        print("No internal links found to visit.")
        return

    # Get a random sample of links to visit
    links_to_visit = random.sample(list(link_urls), min(len(link_urls), max_to_visit))

    print(f"Found {len(links_to_visit)} internal link(s) to visit.")

    for url in links_to_visit:
        if stop_event.is_set():
            return

        try:
            print(f"Visiting internal link: {url}")
            driver.get(url)
            # Simulate user reading the page
            min_sleep = config["timing"]["sleepMin"]
            max_sleep = config["timing"]["sleepMax"]
            time.sleep(random.uniform(min_sleep, max_sleep))
        except Exception as e:
            print(f"Error visiting internal link {url}: {e}")


def run_session(keyword, config, engine_name, engine, stop_event, stats):
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

            with _STATS_LOCK:
                stats["success"].append({"keyword": keyword, "engine": engine_name})

            visit_website(driver, config, stop_event)
            _click_internal_links(driver, config, stop_event)

        else:
            print(f"Website not found. [{engine_name}]")

            with _STATS_LOCK:
                stats["failed"].append({"keyword": keyword, "engine": engine_name})

    except Exception as error:
            if not stop_event.is_set():
                
                with _STATS_LOCK:
                    stats["failed"].append({"keyword": keyword, "engine": engine_name})

                print(f"Session Error ({keyword} | {engine_name}): {error}")

    finally:
        if driver:
            _unregister_driver(driver)
            close_browser(driver)


def _session_worker(job_queue, config, stop_event, stats):
    while not stop_event.is_set():
        try:
            keyword, engine_name, engine = job_queue.get_nowait()
        except queue.Empty:
            return

        try:
            run_session(keyword, config, engine_name, engine, stop_event, stats)
        except Exception as error:
            print(f"Session Error: {error}")
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

    try:
        for worker in workers:
            worker.start()

        while any(worker.is_alive() for worker in workers):
            for worker in workers:
                worker.join(timeout=0.2)

        return stats

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

        return stats
