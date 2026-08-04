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
import time

from browser.browser import setup_browser, close_browser

from automation.youtube import (
    open_youtube,
    search_video,
    find_target_video,
    watch_video,
    go_to_home,
    close_mini_player,
)

from utils.logger import write_log

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


def retry_operation(operation, retries=3, delay=3):
    """
    Retry an operation before giving up.
    """

    for attempt in range(1, retries + 1):

        try:
            result = operation()

            # Success
            return True, result

        except Exception as error:

            print(
                f"Retry {attempt}/{retries} failed : {error}"
            )

            if attempt < retries:
                time.sleep(delay)

    return False, None


def run_session( keywords, config, stop_event):
    """
    Run one complete YouTube automation session.
    """

    driver = None

    browser_name = threading.current_thread().name.replace("Thread-", "Browser-")

    try:

        if stop_event.is_set():
            return

        print(f"\n[{browser_name}] Starting YouTube Session")

        write_log(
          browser_name,
          "Session Started"
        )

        driver = setup_browser(config)
        _register_driver(driver)

        if stop_event.is_set():
            return

        open_youtube(
                driver,
                config,
                stop_event,
        )

        if stop_event.is_set():
          return

        for keyword in keywords:

           print(f"\n[{browser_name}] Searching keyword : {keyword}")

           success, _ = retry_operation(
                lambda: search_video(
                        driver,
                        keyword,
                        config,
                        stop_event,
                )
            )

           if not success:
             print(
              f"[{browser_name}] Failed to search keyword : {keyword}"
            )
             continue

           if stop_event.is_set():
             return

           success, found = retry_operation(
                  lambda: find_target_video(
                        driver,
                        config,
                        stop_event,
                     )
            )

           if not success:
              print(
                   f"[{browser_name}] Failed while finding target video."
            )
              continue

           if stop_event.is_set():
            return

           if found:
            print(f"[{browser_name}] Target channel video found.")

            watch_video(
              driver,
              config,
              stop_event,
            )

            if stop_event.is_set():
             return

            go_to_home(
               driver,
               config,
               stop_event,
            )

            close_mini_player(driver)

           else:
             print(f"[{browser_name}] Target channel video not found.")

    except Exception as error:

     if not stop_event.is_set():
        print(f"[{browser_name}] YouTube Session Error : {error}")

    finally:
 
     if driver:
        try:
            close_browser(driver)
        finally:
            _unregister_driver(driver)


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
    browsers = config["browser"]["browsers"]

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

        return not stop_event.is_set()

    except KeyboardInterrupt:

     print("\nCtrl+C detected. Stopping automation...")

     stop_event.set()

    # close_active_drivers()   <-- Is line ko comment kar do

     for worker in workers:
        worker.join()

     print("Automation stopped.")

     return False