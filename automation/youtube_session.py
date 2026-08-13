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

from automation.search_engine_selector import select_search_engine
from utils.session_stats import SessionStats

from browser.browser_selector import select_browser

from browser.browser import setup_browser, close_browser

from automation.search_engine import (
    open_search_engine,
    search_keyword,
    find_target_website,
)

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
    stats=None,
    driver=None,
    operation_name="operation",
):
    """
    Retry an operation only when the browser session
    is still alive.

    A dead/unresponsive browser is not retried blindly.
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

            if stats:
                stats.record_retry()

            print(
                f"[RETRY] {operation_name} "
                f"failed ({attempt}/{retries}) : {error}"
            )

            # ---------------------------------------------
            # Browser health check
            # ---------------------------------------------

            if driver is not None:

                if not is_browser_alive(driver):

                    print(
                        f"[RETRY] {operation_name} : "
                        f"browser session is no longer alive."
                    )

                    return False, None

            # ---------------------------------------------
            # Wait before retry
            # ---------------------------------------------

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

    if not driver:
        return False

    try:

        driver.current_url

        return True

    except Exception as error:

        print(
            f"[BROWSER] Health check failed : {error}"
        )

        return False


def run_session(
    keywords,
    config,
    search_engines,
    stop_event,
    stats,
):
    """
    Run one complete YouTube automation session.
    """

    driver = None
    session_success = True

    thread_name = threading.current_thread().name.replace(
        "Thread-",
        "Browser-"
    )

    selected_browser = select_browser(config)
    selected_search_engine = select_search_engine(config)

    try:

        engine_config = search_engines[selected_search_engine]

    except KeyError:

        print(
            f"[{thread_name}] Invalid search engine : "
            f"{selected_search_engine}"
        )

        stats.record_failure()
        return

    stats.record_browser(selected_browser)

    print(
        f"\n[{thread_name}] Selected Browser : "
        f"{selected_browser}"
    )

    print(
        f"[{thread_name}] Selected Search Engine : "
        f"{selected_search_engine}"
    )

    try:

        if stop_event.is_set():
            return

        print(
            f"\n[{thread_name}]"
            f"[{selected_browser.upper()}] "
            f"Starting YouTube Session"
        )

        write_log(
            f"{thread_name}[{selected_browser.upper()}]",
            "Session Started"
        )

        # --------------------------------
        # Start Browser
        # --------------------------------

        try:

            driver = setup_browser(
                config,
                selected_browser,
            )

            _register_driver(driver)

        except Exception as error:

            session_success = False
            stats.record_browser_error()

            print(
                f"[{thread_name}]"
                f"[{selected_browser.upper()}] "
                f"Browser startup failed : {error}"
            )

            return

        if stop_event.is_set():
            return

        # --------------------------------
        # Process Keywords
        # --------------------------------

        for keyword in keywords:

            if stop_event.is_set():
                return

            stats.record_keyword()

            if not is_browser_alive(driver):

                session_success = False
                stats.record_browser_error()

                print(
                    f"[{thread_name}]"
                    f"[{selected_browser.upper()}] "
                    f"Browser session disconnected."
                )

                return

            # --------------------------------
            # Search Engine
            # --------------------------------

            print(
                f"\n[{thread_name}]"
                f"[{selected_browser.upper()}] "
                f"[{selected_search_engine.upper()}] "
                f"Processing keyword : {keyword}"
            )

            search_success, _ = retry_operation(
                lambda: (
                    open_search_engine(
                        driver,
                        engine_config,
                    ),
                    search_keyword(
                        driver,
                        engine_config,
                        keyword,
                        config,
                        stop_event,
                    ),
                ),
                stop_event=stop_event,
                stats=stats,
                driver=driver,
                operation_name="Search Engine",
            )

            if not search_success:

                session_success = False
                stats.record_search_error()
                stats.record_keyword_failure()

                print(
                    f"[{thread_name}]"
                    f"[{selected_search_engine.upper()}] "
                    f"Failed to process search keyword : "
                    f"{keyword}"
                )

                if not is_browser_alive(driver):
                    stats.record_browser_error()
                    return

                continue

            if stop_event.is_set():
                return

            print(
                f"[{thread_name}] "
                f"{selected_search_engine.upper()} "
                f"search completed."
            )

            # --------------------------------
            # Return to YouTube
            # --------------------------------

            youtube_success, youtube_opened = retry_operation(
                lambda: open_youtube(
                    driver,
                    config,
                    stop_event,
                ),
                stop_event=stop_event,
                stats=stats,
                driver=driver,
                operation_name="Open YouTube",
            )

            if not youtube_success or not youtube_opened:

                session_success = False
                stats.record_browser_error()
                stats.record_keyword_failure()

                print(
                    f"[{thread_name}] "
                    f"Failed to open YouTube for keyword : "
                    f"{keyword}"
                )

                if not is_browser_alive(driver):
                    return

                continue

            if stop_event.is_set():
                return

            # --------------------------------
            # YouTube Search
            # --------------------------------

            print(
                f"\n[{thread_name}]"
                f"[{selected_browser.upper()}] "
                f"Searching keyword on YouTube : "
                f"{keyword}"
            )

            success, _ = retry_operation(
                lambda: search_video(
                    driver,
                    keyword,
                    config,
                    stop_event,
                ),
                stop_event=stop_event,
                stats=stats,
                driver=driver,
                operation_name="YouTube Search",
            )

            if not success:

                session_success = False
                stats.record_keyword_failure()

                print(
                    f"[{thread_name}]"
                    f"[{selected_browser.upper()}] "
                    f"Failed to search keyword : "
                    f"{keyword}"
                )

                if not is_browser_alive(driver):
                    stats.record_browser_error()
                    return

                continue

            if stop_event.is_set():
                return

            # --------------------------------
            # Find Target Video
            # --------------------------------

            success, found = retry_operation(
                lambda: find_target_video(
                    driver,
                    config,
                    stop_event,
                ),
                stop_event=stop_event,
                stats=stats,
                driver=driver,
                operation_name="Find Target Video",
            )

            if not success:

                session_success = False
                stats.record_keyword_failure()

                print(
                    f"[{thread_name}]"
                    f"[{selected_browser.upper()}] "
                    f"Failed while finding target video."
                )

                if not is_browser_alive(driver):
                    stats.record_browser_error()
                    return

                continue

            if stop_event.is_set():
                return

            # --------------------------------
            # Watch Video
            # --------------------------------

            if found:

                stats.record_video_found()

                print(
                    f"[{thread_name}]"
                    f"[{selected_browser.upper()}] "
                    f"Target channel video found."
                )

                watch_time = watch_video(
                    driver,
                    config,
                    stop_event,
                )

                stats.record_watch_time(
                    watch_time
                )

                if stop_event.is_set():
                    return

                # --------------------------------
                # Return to YouTube Home
                # --------------------------------

                go_to_home(
                    driver,
                    config,
                    stop_event,
                )

                close_mini_player(driver)

            else:

                stats.record_video_not_found()

                print(
                    f"[{thread_name}]"
                    f"[{selected_browser.upper()}] "
                    f"Target channel video not found."
                )

        # --------------------------------
        # Session Completed
        # --------------------------------

        if session_success:

            stats.record_success()

        else:

            stats.record_failure()

    except Exception as error:

        session_success = False

        if not stop_event.is_set():

            stats.record_failure()

            print(
                f"[{thread_name}]"
                f"[{selected_browser.upper()}] "
                f"YouTube Session Error : {error}"
            )

            traceback.print_exc()

    finally:

        if driver:

            try:

                close_browser(driver)

            except Exception as error:

                print(
                    f"[{thread_name}] "
                    f"Browser close error : {error}"
                )

            finally:

                _unregister_driver(driver)


def _session_worker(keywords, config,search_engines, stop_event, stats,):
    """
    Worker thread that runs one browser session.
    """

    print(f"Worker Started : {threading.current_thread().name}")

    run_session(
        keywords,
        config,
        search_engines,
        stop_event,
        stats,
    )


def start_parallel_sessions(keywords, config, search_engines):
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
                search_engines,
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