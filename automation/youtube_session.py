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

import queue
import threading

from browser.browser import setup_browser, close_browser

from automation.youtube import (
    open_youtube,
    search_video,
    find_target_video,
    watch_video,
)

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


def run_session(keywords, config, stop_event):
    """
    Run one complete YouTube automation session.
    """

    driver = None

    try:

        if stop_event.is_set():
            return

        print(f"\nStarting YouTube Session")

        driver = setup_browser(config)
        _register_driver(driver)

        if stop_event.is_set():
            return

        open_youtube(driver)

        if stop_event.is_set():
          return

        for keyword in keywords:

           print(f"\nSearching keyword : {keyword}")

           search_video(
             driver,
             keyword,
             config,
             stop_event,
            )

           if stop_event.is_set():
             return

           found = find_target_video(
             driver,
             config,
             stop_event,
            )

           if stop_event.is_set():
            return

           if found:
            print("Target channel video found.")

            watch_video(
              driver,
              config,
              stop_event,
            )

           else:
            print("Target channel video not found.")

    except Exception as error:

     if not stop_event.is_set():
        print(f"YouTube Session Error : {error}")

    finally:

        if driver:
            _unregister_driver(driver)
            close_browser(driver)


def _session_worker(keywords, config, stop_event):
    """
    Worker thread that runs one browser session.
    """

    print(f"Worker Started : {threading.current_thread().name}")

    run_session(
        keywords,
        config,
        stop_event,
    )


def start_parallel_sessions(keywords, config):
    """
    Start multiple YouTube sessions in parallel.
    """

    max_workers = int(config["sessions"]["parallel"])

    stop_event = threading.Event()

    workers = [
        threading.Thread(
            target=_session_worker,
            args=(
                keywords,
                config,
                stop_event,
            ),
            daemon=True,
        )
        for _ in range(max_workers)
    ]

    try:

        for worker in workers:
            worker.start()

        for worker in workers:
            worker.join()

        return not stop_event.is_set()

    except KeyboardInterrupt:

        print("\nCtrl+C detected. Stopping automation...")

        stop_event.set()

        close_active_drivers()

        for worker in workers:
            worker.join(timeout=2)

        print("Automation stopped.")

        return False