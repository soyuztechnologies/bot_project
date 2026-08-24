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
import random
import logging
import queue
from datetime import datetime
import uuid

from automation.search_engine_selector import select_search_engine
from utils.session_stats import SessionStats
from utils.database import create_automation_run, update_automation_run

from browser.browser_selector import select_browser

from browser.browser import setup_browser, close_browser
from .search_engine import is_google_verification_page

from automation.search_engine import (
    open_search_engine,
    search_keyword,
    find_target_website,
    open_video_tab,
    find_target_video_in_video_results,
)

from automation.youtube import (
    YOUTUBE,
    open_youtube,
    search_video,
    find_target_video,
    watch_video,
    go_to_home,
    close_mini_player,
)

from utils.logger import write_log
from utils.helpers import random_sleep

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

_ACTIVE_DRIVERS = set()
_STATS_LOCK = threading.Lock()
logger = logging.getLogger(__name__)
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
    retry_tracker=None,
    session_logger=None,
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

            if retry_tracker is not None:
                retry_tracker["count"] = retry_tracker.get("count", 0) + 1

            if session_logger is not None:
                session_logger.warning(
                    f"Operation failed on attempt {attempt}/{retries}",
                    exc_info=True,
                    extra={
                        "action": "RETRY_OPERATION",
                        "status": "FAILED",
                        "error_message": str(error),
                    },
                )

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


def process_youtube_first_flow(
    driver,
    keyword,
    config,
    stop_event,
    stats,
    thread_name,
    selected_browser,
    retry_tracker=None,
):
    """
    CASE 1:
    Open YouTube directly, search the keyword,
    find Anubhav Trainings video, and watch it.
    """

    # --------------------------------
    # Open YouTube
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
        retry_tracker=retry_tracker,
    )

    if not youtube_success or not youtube_opened:

        print(
            f"[{thread_name}] "
            f"Failed to open YouTube for keyword : "
            f"{keyword}"
        )

        return False

    if stop_event.is_set():
        return False

    # --------------------------------
    # Search Keyword on YouTube
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
        retry_tracker=retry_tracker,
    )

    if not success:

        print(
            f"[{thread_name}]"
            f"[{selected_browser.upper()}] "
            f"Failed to search keyword : "
            f"{keyword}"
        )

        return False

    if stop_event.is_set():
        return False

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
        retry_tracker=retry_tracker,
    )

    if not success:

        print(
            f"[{thread_name}]"
            f"[{selected_browser.upper()}] "
            f"Failed while finding target video."
        )

        return False

    if stop_event.is_set():
        return False

    # ---------------------------------------------------------
    # Vipul fallback keyword support
    # ---------------------------------------------------------
    if not found:
        extra_keyword = config.get("youtube", {}).get("extra_keyword", "").strip()

        if extra_keyword and extra_keyword.lower() not in keyword.lower():
            fallback_keyword = f"{keyword} {extra_keyword}"

            print(
                f"[{thread_name}] "
                f"[{selected_browser.upper()}] "
                f"Target video not found. "
                f"Retrying with fallback keyword : {fallback_keyword}"
            )

            fallback_success, _ = retry_operation(
                lambda: search_video(
                    driver,
                    fallback_keyword,
                    config,
                    stop_event,
                ),
                stop_event=stop_event,
                stats=stats,
                driver=driver,
                operation_name="YouTube Fallback Search",
                retry_tracker=retry_tracker,
            )

            if fallback_success and not stop_event.is_set():
                fallback_find_success, fallback_found = retry_operation(
                    lambda: find_target_video(
                        driver,
                        config,
                        stop_event,
                    ),
                    stop_event=stop_event,
                    stats=stats,
                    driver=driver,
                    operation_name="Find Target Video - Fallback",
                    retry_tracker=retry_tracker,
                )
                if fallback_find_success:
                    found = fallback_found

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

        stats.record_watch_time(watch_time)

        if stop_event.is_set():
            return False

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

    return True


def _safe_create_automation_run(run_id, keyword, config, selected_browser):
    """Create Vipul's DB record without breaking automation if DB is unavailable."""
    try:
        youtube_config = config.get("youtube", {})
        create_automation_run(
            run_id=run_id,
            automation_type="YOUTUBE",
            original_keyword=keyword,
            search_keyword=keyword,
            browser_mode=str(selected_browser).capitalize(),
            target=youtube_config.get("targetChannel", ""),
            search_engine="youtube",
        )
    except Exception as error:
        logger.warning(
            f"Could not create automation DB record for '{keyword}': {error}",
            exc_info=True,
        )


def _safe_update_automation_run(
    run_id,
    keyword,
    status,
    retry_count=0,
    fallback_used=False,
    search_keyword=None,
):
    """Update Vipul's DB record without breaking automation if DB is unavailable."""
    if run_id is None:
        return

    try:
        update_automation_run(
            run_id=run_id,
            finished_at=datetime.now(),
            status=status,
            success_count=1 if status == "SUCCESS" else 0,
            failure_count=1 if status == "FAILED" else 0,
            retry_count=retry_count,
            fallback_used=fallback_used,
            search_keyword=search_keyword or keyword,
        )
    except Exception as error:
        logger.warning(
            f"Could not update automation DB record for '{keyword}': {error}",
            exc_info=True,
        )

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

    # Vipul database state: one automation_run per keyword.
    run_ids = {}
    retry_trackers = {}

    thread_name = threading.current_thread().name.replace(
        "Thread-",
        "Browser-"
    )

    selected_browser = select_browser(config)
    selected_search_engine = select_search_engine(config)

    # ---------------------------------------------------------
    # TEMPORARY:
    # We are testing Case 2 first.
    # Later this will become random flow selection.
    # ---------------------------------------------------------

    flow = random.choice([
            "youtube_first",
            "search_engine_first",
    ])

    # flow = "search_engine_first"

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

    print(
        f"[{thread_name}] Selected Flow : "
        f"{flow}"
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

        # =====================================================
        # START BROWSER
        # =====================================================

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
            traceback.print_exc()

            return

        if stop_event.is_set():
            return

        # =====================================================
        # PROCESS KEYWORDS
        # =====================================================

        for keyword in keywords:

            if stop_event.is_set():
                return

            stats.record_keyword()

            # -------------------------------------------------
            # Vipul database tracking
            # -------------------------------------------------
            run_ids[keyword] = uuid.uuid4()
            retry_trackers[keyword] = {"count": 0}
            _safe_create_automation_run(
                run_ids[keyword],
                keyword,
                config,
                selected_browser,
            )

            # -------------------------------------------------
            # Check browser
            # -------------------------------------------------

            if not is_browser_alive(driver):

                session_success = False
                stats.record_browser_error()

                print(
                    f"[{thread_name}]"
                    f"[{selected_browser.upper()}] "
                    f"Browser session disconnected."
                )

                return

            # =================================================
            # CASE 1 - YOUTUBE FIRST
            # =================================================

            if flow == "youtube_first":

                print(
                    f"\n[{thread_name}]"
                    f"[{selected_browser.upper()}] "
                    f"[YOUTUBE_FIRST] "
                    f"Processing keyword : {keyword}"
                )

                success = process_youtube_first_flow(
                    driver,
                    keyword,
                    config,
                    stop_event,
                    stats,
                    thread_name,
                    selected_browser,
                    retry_tracker=retry_trackers.get(keyword),
                )

                if not success:

                    session_success = False
                    stats.record_keyword_failure()

                    _safe_update_automation_run(
                        run_ids.get(keyword),
                        keyword,
                        "FAILED",
                        retry_count=retry_trackers.get(keyword, {}).get("count", 0),
                        fallback_used=False,
                        search_keyword=keyword,
                    )

                    if not is_browser_alive(driver):

                        stats.record_browser_error()
                        return

                else:
                    extra_keyword = config.get("youtube", {}).get("extra_keyword", "").strip()
                    fallback_used = bool(
                        extra_keyword and extra_keyword.lower() not in keyword.lower()
                    )
                    _safe_update_automation_run(
                        run_ids.get(keyword),
                        keyword,
                        "SUCCESS",
                        retry_count=retry_trackers.get(keyword, {}).get("count", 0),
                        fallback_used=fallback_used,
                        search_keyword=(
                            f"{keyword} {extra_keyword}"
                            if fallback_used else keyword
                        ),
                    )

                continue

            # =================================================
            # CASE 2 - SEARCH ENGINE FIRST
            # =================================================

            print(
                f"\n[{thread_name}]"
                f"[{selected_browser.upper()}] "
                f"[SEARCH_ENGINE_FIRST] "
                f"Processing keyword : {keyword}"
            )

            # -------------------------------------------------
            # Target Channel Configuration
            # -------------------------------------------------

            youtube_config = config.get(
                "youtube",
                {}
            )

            target_channel = youtube_config["targetChannel"]

            max_search_pages = youtube_config["maxSearchPages"]

            # -------------------------------------------------
            # Search Engine Fallback Order
            # -------------------------------------------------

            fallback_engines = config["search"]["engines"]

            keyword_completed = False
            target_video_found = False

            # -------------------------------------------------
            # Try each configured search engine
            # -------------------------------------------------

            for current_engine in fallback_engines:

                if stop_event.is_set():
                    return

                # -------------------------------------------------
                # Skip engine if it is not configured
                # -------------------------------------------------

                if current_engine not in search_engines:

                    print(
                        f"[{thread_name}] "
                        f"{current_engine.upper()} is not configured. "
                        f"Skipping."
                    )

                    continue

                current_engine_config = search_engines[
                    current_engine
                ]

                print()
                print(
                    "=" * 60
                )

                print(
                    f"[{thread_name}] "
                    f"Trying Search Engine : "
                    f"{current_engine.upper()}"
                )

                print(
                    f"Keyword : {keyword}"
                )

                print(
                    "=" * 60
                )

                # -------------------------------------------------
                # Clear previous target URL
                # -------------------------------------------------

                driver.target_video_url = None

                # -------------------------------------------------
                # 1. Open Search Engine + Search Keyword
                # -------------------------------------------------

                search_success, _ = retry_operation(

                    lambda: (
                        open_search_engine(
                            driver,
                            current_engine_config,
                        ),

                        search_keyword(
                            driver,
                            current_engine_config,
                            keyword,
                            config,
                            stop_event,
                        ),
                    ),

                    stop_event=stop_event,
                    stats=stats,
                    driver=driver,
                    operation_name=(
                        f"{current_engine.upper()} Search Engine"
                    ),
                    retry_tracker=retry_trackers.get(keyword),
                )

                if not search_success:

                    print(
                        f"[{thread_name}] "
                        f"{current_engine.upper()} "
                        f"search failed."
                    )

                    print(
                        f"[{thread_name}] "
                        f"Trying next search engine..."
                    )

                    continue

                if stop_event.is_set():
                    return

                print(
                    f"[{thread_name}] "
                    f"{current_engine.upper()} "
                    f"search completed."
                )

                # -------------------------------------------------
                # Google verification check
                # -------------------------------------------------

                if current_engine == "google":

                    if is_google_verification_page(driver):

                        print()
                        print(
                            "[SEARCH ENGINE] "
                            "Google verification detected."
                        )

                        print(
                            "[SEARCH ENGINE] "
                            "Google unavailable for this keyword."
                        )

                        print(
                            "[SEARCH ENGINE] "
                            "Switching to next search engine..."
                        )

                        continue

                # -------------------------------------------------
                # DuckDuckGo promo popup
                # -------------------------------------------------

                if current_engine == "duckduckgo":

                    try:

                        close_button = driver.find_element(
                            By.CSS_SELECTOR,
                            '[data-testid="serp-popover-promo-close"]'
                        )

                        close_button.click()

                        print(
                            "DUCKDUCKGO promo popup closed."
                        )

                    except Exception:

                        print(
                            "DUCKDUCKGO promo popup not found."
                        )

                # -------------------------------------------------
                # 2. Open Videos Tab
                # -------------------------------------------------

                print(
                    f"[{thread_name}] "
                    f"[{current_engine.upper()}] "
                    f"Opening Videos tab..."
                )

                video_tab_success = open_video_tab(
                    driver,
                    current_engine_config,
                    config,
                    stop_event,
                )

                if not video_tab_success:

                    print(
                        f"[{thread_name}] "
                        f"[{current_engine.upper()}] "
                        f"Failed to open Videos tab."
                    )

                    print(
                        f"[{thread_name}] "
                        f"Trying next search engine..."
                    )

                    continue

                if stop_event.is_set():
                    return

                # -------------------------------------------------
                # 3. Find Target Video
                # -------------------------------------------------

                print(
                    f"[{thread_name}] "
                    f"[{current_engine.upper()}] "
                    f"Searching Videos results for target "
                    f"channel : {target_channel}"
                )

                video_success, found = retry_operation(

                    lambda: find_target_video_in_video_results(
                        driver,
                        current_engine_config,
                        target_channel,
                        max_search_pages,
                        stop_event,
                        YOUTUBE,
                    ),

                    stop_event=stop_event,
                    stats=stats,
                    driver=driver,
                    operation_name=(
                        f"Find Target Video - "
                        f"{current_engine.upper()}"
                    ),
                    retry_tracker=retry_trackers.get(keyword),
                )

                if not video_success:

                    print(
                        f"[{thread_name}] "
                        f"[{current_engine.upper()}] "
                        f"Error while searching target video."
                    )

                    print(
                        f"[{thread_name}] "
                        f"Trying next search engine..."
                    )

                    continue

                if stop_event.is_set():
                    return

                # -------------------------------------------------
                # Target Video Found
                # -------------------------------------------------

                if found:

                    target_video_url = getattr(
                        driver,
                        "target_video_url",
                        None,
                    )

                    if not target_video_url:

                        print(
                            f"[{thread_name}] "
                            f"[{current_engine.upper()}] "
                            f"Target video found but URL was not stored."
                        )

                        print(
                            f"[{thread_name}] "
                            f"Trying next search engine..."
                        )

                        continue

                    # -------------------------------------------------
                    # SUCCESSFUL SEARCH ENGINE
                    # -------------------------------------------------

                    print()
                    print(
                        "=" * 60
                    )

                    print(
                        f"[{thread_name}] "
                        f"TARGET VIDEO FOUND"
                    )

                    print(
                        f"Search Engine : "
                        f"{current_engine.upper()}"
                    )

                    print(
                        f"Target Channel : "
                        f"{target_channel}"
                    )

                    print(
                        f"Target Video URL : "
                        f"{target_video_url}"
                    )

                    print(
                        "=" * 60
                    )

                    stats.record_video_found()

                    target_video_found = True
                    keyword_completed = True

                    # -------------------------------------------------
                    # 4. Open Exact Target Video
                    # -------------------------------------------------

                    print(
                        f"[{thread_name}] "
                        f"[{selected_browser.upper()}] "
                        f"Opening target video : "
                        f"{target_video_url}"
                    )

                    driver.get(
                        target_video_url
                    )

                    random_sleep(
                        2,
                        4,
                        stop_event,
                    )

                    if stop_event.is_set():
                        return

                    # -------------------------------------------------
                    # Give YouTube time to load
                    # -------------------------------------------------

                    random_sleep(
                        config["timing"]["sleepMin"],
                        config["timing"]["sleepMax"],
                        stop_event,
                    )

                    if stop_event.is_set():
                        return

                    # -------------------------------------------------
                    # 5. Watch Video
                    # -------------------------------------------------

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

                    # -------------------------------------------------
                    # 6. Return to YouTube Home
                    # -------------------------------------------------

                    go_to_home(
                        driver,
                        config,
                        stop_event,
                    )

                    close_mini_player(
                        driver
                    )

                    _safe_update_automation_run(
                        run_ids.get(keyword),
                        keyword,
                        "SUCCESS",
                        retry_count=retry_trackers.get(keyword, {}).get("count", 0),
                        fallback_used=False,
                        search_keyword=keyword,
                    )

                    # -------------------------------------------------
                    # Target found -> stop engine fallback
                    # -------------------------------------------------

                    break

                # -------------------------------------------------
                # Target Video NOT Found
                # -------------------------------------------------

                else:

                    stats.record_video_not_found()

                    print(
                        f"[{thread_name}] "
                        f"[{current_engine.upper()}] "
                        f"Target channel video not found."
                    )

                    print(
                        f"[{thread_name}] "
                        f"Trying next search engine..."
                    )

            # -------------------------------------------------
            # All Search Engines Exhausted
            # -------------------------------------------------

            if not keyword_completed:

                session_success = False

                stats.record_keyword_failure()

                _safe_update_automation_run(
                    run_ids.get(keyword),
                    keyword,
                    "FAILED",
                    retry_count=retry_trackers.get(keyword, {}).get("count", 0),
                    fallback_used=False,
                    search_keyword=keyword,
                )

                print()
                print(
                    "=" * 60
                )

                print(
                    f"[{thread_name}] "
                    f"All search engines exhausted."
                )

                print(
                    f"[{thread_name}] "
                    f"Target video could not be processed "
                    f"for keyword : {keyword}"
                )

                print(
                    "=" * 60
                )

                if not is_browser_alive(driver):

                    stats.record_browser_error()

                    return

        # =====================================================
        # SESSION COMPLETED
        # =====================================================

        if session_success:

            stats.record_success()

        else:

            stats.record_failure()

    # =========================================================
    # UNEXPECTED SESSION ERROR
    # =========================================================

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

    # =========================================================
    # CLOSE BROWSER
    # =========================================================

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
def start_parallel_sessions_with_queue(keywords, config, search_engines, stats=None):
    """
    Vipul-compatible queue-based parallel runner.

    The original start_parallel_sessions() is retained. This additional entry point
    provides queue scheduling while using the merged run_session().
    """
    keywords = list(keywords)
    stats = stats or SessionStats()

    max_workers = min(int(config["sessions"]["parallel"]), len(keywords))
    stop_event = threading.Event()
    job_queue = queue.Queue()

    random.shuffle(keywords)
    for keyword in keywords:
        job_queue.put(keyword)

    workers = []

    def _queued_worker():
        while not stop_event.is_set():
            try:
                keyword = job_queue.get_nowait()
            except queue.Empty:
                return

            try:
                run_session(
                    [keyword],
                    config,
                    search_engines,
                    stop_event,
                    stats,
                )
            except Exception as error:
                logger.error(
                    f"Unhandled queued session error for '{keyword}': {error}",
                    exc_info=True,
                )
            finally:
                job_queue.task_done()

    for _ in range(max_workers):
        workers.append(
            threading.Thread(target=_queued_worker, daemon=True)
        )

    try:
        for worker in workers:
            worker.start()

        while job_queue.unfinished_tasks > 0:
            time.sleep(0.5)

    except KeyboardInterrupt:
        logger.info("Ctrl+C detected. Stopping automation...")
        stop_event.set()
        raise

    finally:
        stop_event.set()
        close_active_drivers()
        for worker in workers:
            worker.join(timeout=2)

    return stats
