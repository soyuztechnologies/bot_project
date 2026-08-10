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

import threading
import time
import traceback

from utils.session_stats import SessionStats

from browser.browser_selector import select_browser

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

    print(f"Remaining active drivers : {len(drivers)}")

    for driver in drivers:
        try:
            print("Closing remaining browser...")
            close_browser(driver)
            print("Remaining browser closed.")
        except Exception as error:
            print(f"Failed to close remaining browser : {error}")


def retry_operation(
    operation,
    retries=3,
    delay=3,
    stop_event=None,
):
    """
    Retry an operation before giving up.
    """

    for attempt in range(1, retries + 1):

        if stop_event and stop_event.is_set():
            return False, None

        try:
            result = operation()

            return True, result

        except Exception as error:

            if stop_event and stop_event.is_set():
                return False, None

            print(
                f"Retry {attempt}/{retries} failed : {error}"
            )

            if attempt < retries:

                if stop_event:
                    if stop_event.wait(delay):
                        return False, None
                else:
                    time.sleep(delay)

    return False, None


def is_browser_alive(driver):
    """
    Check whether the browser session is still alive.
    """

    try:
        driver.current_url
        return True
    except Exception:
        return False


def run_session( keywords, config, stop_event,stats):
    """
    Run one complete YouTube automation session.
    """

    driver = None

    # success = False

    thread_name = threading.current_thread().name.replace(
                            "Thread-",
                            "Browser-"
     )
    selected_browser = select_browser(config)

    stats.record_browser(selected_browser) 


    print(
    f"\n[{thread_name}] Selected Browser : {selected_browser}")

    try:

        if stop_event.is_set():
            return

        print(f"\n[{thread_name}][{selected_browser.upper()}] Starting YouTube Session")

        write_log(
            f"{thread_name}[{selected_browser.upper()}]",
             "Session Started"
        )

        driver = setup_browser(
            config,
            selected_browser,
        )
        _register_driver(driver)

        if stop_event.is_set():
            return

        youtube_opened = open_youtube(
            driver,
            config,
            stop_event,
        )

        if not youtube_opened:
         return

        if stop_event.is_set():
          return

        for keyword in keywords:

           stats.record_keyword()

           if stop_event.is_set():
               return
 
           if not is_browser_alive(driver):
               print(f"[{thread_name}][{selected_browser.upper()}] Browser session disconnected.")
               return

           print(f"\n[{thread_name}][{selected_browser.upper()}] Searching keyword : {keyword}")

           success, _ = retry_operation(
                lambda: search_video(
                        driver,
                        keyword,
                        config,
                        stop_event,
                ),
                stop_event=stop_event,
            )

           if not success:
             print(
              f"[{thread_name}][{selected_browser.upper()}] Failed to search keyword : {keyword}"
            )
             continue

           if stop_event.is_set():
             return

           success, found = retry_operation(
                  lambda: find_target_video(
                        driver,
                        config,
                        stop_event,
                     ),
                     stop_event=stop_event,
            )

           if not success:
              print(
                   f"[{thread_name}][{selected_browser.upper()}] Failed while finding target video."
            )
              continue

           if stop_event.is_set():
            return

           if found:
            stats.record_video_found()
            print(f"[{thread_name}][{selected_browser.upper()}] Target channel video found.")

            watch_time = watch_video(
             driver,
             config,
             stop_event,
            )

            stats.record_watch_time(watch_time)

            if stop_event.is_set():
             return

            go_to_home(
               driver,
               config,
               stop_event,
            )

            close_mini_player(driver)

           else:
             stats.record_video_not_found()
             print(f"[{thread_name}][{selected_browser.upper()}] Target channel video not found.")

            #  success = True

    except Exception as error:

     if not stop_event.is_set():

        print(f"[{thread_name}][{selected_browser.upper()}] YouTube Session Error : {error}")

        traceback.print_exc()

    finally:

     stats.record_success()
 
     if driver:
        try:
            close_browser(driver)
        finally:
            _unregister_driver(driver)


def _session_worker(keywords, config, stop_event, stats,):
    """
    Worker thread that runs one browser session.
    """

    print(f"Worker Started : {threading.current_thread().name}")

    run_session(
        keywords,
        config,
        stop_event,
        stats,
    )


def start_parallel_sessions(keywords, config):
    """
    Start multiple YouTube sessions in parallel.
    """

    max_workers = int(config["sessions"]["parallel"])

    stop_event = threading.Event()

    stats = SessionStats()

    workers = []

    for i in range(max_workers):

     workers.append(
        threading.Thread(
            target=_session_worker,
            args=(
                keywords,
                config,
                stop_event,
                stats,
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

        stats.print_summary()

        return not stop_event.is_set()

    except KeyboardInterrupt:

     print("\nCtrl+C detected. Stopping automation...")

     stop_event.set()

     for worker in workers:
        worker.join()

     print("All workers stopped. Closing remaining browsers...")

     close_active_drivers()

     print("Automation stopped.")

     return False