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
import sys
from datetime import datetime
import uuid

from automation.search_engine_selector import select_search_engine
from utils.session_stats import SessionStats
from utils.database import create_automation_run, update_automation_run
from utils.exceptions import (
    BrowserDiedError,
    BrowserError,
    CaptchaDetectedError,
    ConfigError,
    SearchEngineError,
    SeoBotError,
    TargetNotFoundError,
    UnhandledAutomationError,
    VideoNotFoundError,
    YoutubeError,
    wrap_unexpected,
)

from browser.browser_selector import select_browser

from browser.browser import setup_browser, close_browser
from .search_engine import is_google_verification_page
from automation.search_engine import is_captcha_page

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

# ---------------------------------------------------------
# Session Logger Adapter
# ---------------------------------------------------------
# Keeps session-specific fields such as session_id/run_id
# while also preserving per-log fields such as action,
# status, url and error_message.
# Merges adapter context + call extra (Python <3.8 compatibility)
# ---------------------------------------------------------

class SessionLoggerAdapter(logging.LoggerAdapter):

    def process(self, msg, kwargs):
        adapter_extra = dict(
            self.extra or {}
        )

        call_extra = kwargs.get("extra") or {}

        kwargs["extra"] = {
            **adapter_extra,
            **call_extra,
        }

        return msg, kwargs

# Backwards-compatibility fix for LoggerAdapter in Python < 3.8
if sys.version_info < (3, 8):
    def _process_patched(self, msg, kwargs):
        kwargs.setdefault('extra', {})
        for k, v in self.extra.items():
            kwargs['extra'][k] = v
        return msg, kwargs
    logging.LoggerAdapter.process = _process_patched

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


_CLOSED_DRIVER_IDS = set()

def close_active_drivers(stop_event=None):
    """Close every browser that is currently running — suppresses NewConnectionError spam and avoids double-close."""
    # Silence noisy retry logs before quit
    try:
        from utils.logger import silence_noisy_loggers
        silence_noisy_loggers()
    except Exception:
        pass
    try:
        import logging as _lg
        for _n in ("urllib3", "urllib3.connectionpool", "selenium", "selenium.webdriver.remote.remote_connection"):
            _lg.getLogger(_n).setLevel(_lg.ERROR)
    except Exception:
        pass

    with _ACTIVE_DRIVERS_LOCK:
        drivers = list(_ACTIVE_DRIVERS)

    if not drivers:
        return

    # Deduplicate — don't close same driver twice *if previous close succeeded*
    # Keep failed closes retryable
    to_close = []
    for d in drivers:
        try:
            did = id(d)
            if did in _CLOSED_DRIVER_IDS:
                continue
            # Don't add yet — add only after successful close below
            to_close.append(d)
        except Exception:
            to_close.append(d)

    if not to_close:
        return

    # Only print once per shutdown, not per call
    if not (stop_event and stop_event.is_set()):
        print(f"Remaining active drivers : {len(to_close)}")
        for driver in to_close:
            try:
                print("Closing remaining browser...")
                ok = close_browser(driver, timeout=4.0)
                if ok:
                    try:
                        _CLOSED_DRIVER_IDS.add(id(driver))
                    except Exception:
                        pass
                    print("Remaining browser closed.")
                else:
                    print("Remaining browser forced closed.")
                    try:
                        _CLOSED_DRIVER_IDS.add(id(driver))
                    except Exception:
                        pass
            except Exception as error:
                msg = str(error).lower()
                if "newconnectionerror" not in msg and "connection refused" not in msg:
                    print(f"Failed to close remaining browser : {error}")
    else:
        # On Ctrl+C, close silently to avoid console flood
        for driver in to_close:
            try:
                ok = close_browser(driver, timeout=4.0)
                if ok:
                    try:
                        _CLOSED_DRIVER_IDS.add(id(driver))
                    except Exception:
                        pass
                else:
                    # Force-mark as closed even if forced, to avoid retry loop
                    try:
                        _CLOSED_DRIVER_IDS.add(id(driver))
                    except Exception:
                        pass
            except Exception:
                pass
    # Remove closed drivers from active set
    try:
        with _ACTIVE_DRIVERS_LOCK:
            for d in to_close:
                _ACTIVE_DRIVERS.discard(d)
    except Exception:
        pass


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

                if not is_browser_alive(driver, stop_event):

                    if stop_event and stop_event.is_set():
                        return False, None
                    print(
                        f"[RETRY] {operation_name} : "
                        f"browser session is no longer alive."
                    )

                    if session_logger is not None:
                        try:
                            session_logger.warning(
                                f"Browser died during {operation_name}",
                                extra={
                                    "action": "BROWSER_HEALTH",
                                    "status": "FAILED",
                                },
                            )
                        except Exception:
                            pass

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


def is_browser_alive(driver, stop_event=None):
    """
    Check whether the browser session is still alive.
    Suppresses print spam on Ctrl+C (NewConnectionError).
    """

    if stop_event is not None:
        try:
            if stop_event.is_set():
                return False
        except Exception:
            pass
    if not driver:
        return False

    try:

        driver.current_url

        return True

    except Exception as error:
        msg = str(error).lower()
        if "newconnectionerror" in msg or "connection refused" in msg or "connectionreseterror" in msg or "max retries" in msg or "invalid session" in msg:
            # Suppress spam after Ctrl+C / driver quit — already silenced via logger filter, don't print
            return False
        # Only print for genuine unexpected health failures, not shutdown noise
        if stop_event is None or not stop_event.is_set():
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
    session_logger=None,
):
    """
    CASE 1:
    Open YouTube directly, search the keyword,
    find Anubhav Trainings video, and watch it.
    Supports session_logger for detailed per-keyword logging
    and per-keyword tick/cross stats.
    """

    if session_logger:
        session_logger.info(
            f"[YOUTUBE_FIRST] Starting flow for keyword: '{keyword}' [{selected_browser}]",
            extra={
                "action": "YOUTUBE_FIRST_START",
                "status": "RUNNING",
                "keyword": keyword,
            },
        )

    # --------------------------------
    # Open YouTube
    # --------------------------------

    if session_logger:
        session_logger.info(
            f"Opening YouTube for keyword: {keyword}",
            extra={
                "action": "YOUTUBE_OPEN",
                "status": "RUNNING",
                "keyword": keyword,
            },
        )

    youtube_success, youtube_opened = retry_operation(
        lambda: open_youtube(
            driver,
            config,
            stop_event,
            session_logger=session_logger,
        ),
        stop_event=stop_event,
        stats=stats,
        driver=driver,
        operation_name="Open YouTube",
        retry_tracker=retry_tracker,
        session_logger=session_logger,
    )

    if not youtube_success or not youtube_opened:

        msg = f"[{thread_name}] Failed to open YouTube for keyword : {keyword}"
        print(msg)

        if session_logger:
            session_logger.warning(
                msg,
                extra={
                    "action": "YOUTUBE_OPEN",
                    "status": "FAILED",
                    "keyword": keyword,
                },
            )

        return False

    if stop_event.is_set():
        return False

    if session_logger:
        session_logger.info(
            f"YouTube opened successfully for keyword: {keyword}",
            extra={
                "action": "YOUTUBE_OPEN",
                "status": "SUCCESS",
                "keyword": keyword,
                "url": getattr(driver, "current_url", ""),
            },
        )

    # --------------------------------
    # Search Keyword on YouTube
    # --------------------------------

    print(
        f"\n[{thread_name}]"
        f"[{selected_browser.upper()}] "
        f"Searching keyword on YouTube : "
        f"{keyword}"
    )

    if session_logger:
        session_logger.info(
            f"Searching keyword on YouTube: {keyword}",
            extra={
                "action": "VIDEO_SEARCH_STARTED",
                "status": "RUNNING",
                "keyword": keyword,
            },
        )

    success, _ = retry_operation(
        lambda: search_video(
            driver,
            keyword,
            config,
            stop_event,
            session_logger=session_logger,
        ),
        stop_event=stop_event,
        stats=stats,
        driver=driver,
        operation_name="YouTube Search",
        retry_tracker=retry_tracker,
        session_logger=session_logger,
    )

    if not success:

        msg = f"[{thread_name}][{selected_browser.upper()}] Failed to search keyword : {keyword}"
        print(msg)

        if session_logger:
            session_logger.warning(
                msg,
                extra={
                    "action": "VIDEO_SEARCH_STARTED",
                    "status": "FAILED",
                    "keyword": keyword,
                },
            )

        return False

    if stop_event.is_set():
        return False

    if session_logger:
        session_logger.info(
            f"YouTube search completed for keyword: {keyword}",
            extra={
                "action": "VIDEO_SEARCH_STARTED",
                "status": "SUCCESS",
                "keyword": keyword,
            },
        )

    # --------------------------------
    # Find Target Video
    # --------------------------------

    if session_logger:
        session_logger.info(
            f"Scanning YouTube results for target channel for keyword: {keyword}",
            extra={
                "action": "SCAN_FOR_CHANNEL",
                "status": "RUNNING",
                "keyword": keyword,
            },
        )

    success, found = retry_operation(
        lambda: find_target_video(
            driver,
            config,
            stop_event,
            session_logger=session_logger,
        ),
        stop_event=stop_event,
        stats=stats,
        driver=driver,
        operation_name="Find Target Video",
        retry_tracker=retry_tracker,
        session_logger=session_logger,
    )

    if not success:

        msg = f"[{thread_name}][{selected_browser.upper()}] Failed while finding target video."
        print(msg)

        if session_logger:
            session_logger.warning(
                msg,
                extra={
                    "action": "SCAN_FOR_CHANNEL",
                    "status": "FAILED",
                    "keyword": keyword,
                },
            )

        return False

    if stop_event.is_set():
        return False

    # ---------------------------------------------------------
    #  fallback keyword support
    # ---------------------------------------------------------
    if not found:
        if stop_event.is_set():
            return False
        extra_keyword = config.get("youtube", {}).get("extra_keyword", "").strip()

        if extra_keyword and extra_keyword.lower() not in keyword.lower():
            if stop_event.is_set():
                return False
            fallback_keyword = f"{keyword} {extra_keyword}"

            print(
                f"[{thread_name}] "
                f"[{selected_browser.upper()}] "
                f"Target video not found. "
                f"Retrying with fallback keyword : {fallback_keyword}"
            )

            if session_logger:
                session_logger.info(
                    f"Target not found for '{keyword}', retrying with fallback keyword: '{fallback_keyword}'",
                    extra={
                        "action": "FALLBACK_SEARCH_STARTED",
                        "status": "RUNNING",
                        "keyword": keyword,
                        "fallback_keyword": fallback_keyword,
                    },
                )
                # update search_keyword in adapter context
                try:
                    session_logger.extra["search_keyword"] = fallback_keyword
                except Exception:
                    pass

            fallback_success, _ = retry_operation(
                lambda: search_video(
                    driver,
                    fallback_keyword,
                    config,
                    stop_event,
                    session_logger=session_logger,
                ),
                stop_event=stop_event,
                stats=stats,
                driver=driver,
                operation_name="YouTube Fallback Search",
                retry_tracker=retry_tracker,
                session_logger=session_logger,
            )

            if fallback_success and not stop_event.is_set():
                if session_logger:
                    session_logger.info(
                        f"Fallback search completed for: {fallback_keyword}",
                        extra={
                            "action": "FALLBACK_SEARCH_STARTED",
                            "status": "SUCCESS",
                            "keyword": fallback_keyword,
                        },
                    )
                fallback_find_success, fallback_found = retry_operation(
                    lambda: find_target_video(
                        driver,
                        config,
                        stop_event,
                        session_logger=session_logger,
                    ),
                    stop_event=stop_event,
                    stats=stats,
                    driver=driver,
                    operation_name="Find Target Video - Fallback",
                    retry_tracker=retry_tracker,
                    session_logger=session_logger,
                )
                if fallback_find_success:
                    found = fallback_found
                    if found and session_logger:
                        session_logger.info(
                            f"Fallback target found for keyword: {fallback_keyword}",
                            extra={
                                "action": "SCAN_FOR_CHANNEL",
                                "status": "SUCCESS",
                                "keyword": fallback_keyword,
                            },
                        )

    # --------------------------------
    # Watch Video
    # --------------------------------

    if found:

        stats.record_video_found()
        # Per-keyword tick/cross for summary like main.py
        try:
            stats.record_keyword_success(keyword, "youtube", thread_id=str(threading.get_ident()))
        except Exception:
            pass

        print(
            f"[{thread_name}]"
            f"[{selected_browser.upper()}] "
            f"Target channel video found."
        )

        if session_logger:
            session_logger.info(
                f"Target channel video found for keyword: {keyword}",
                extra={
                    "action": "VIDEO_FOUND",
                    "status": "SUCCESS",
                    "keyword": keyword,
                },
            )

        watch_time = watch_video(
            driver,
            config,
            stop_event,
            session_logger=session_logger,
            keyword=keyword,
        )

        stats.record_watch_time(watch_time)

        if session_logger:
            session_logger.info(
                f"Watch time recorded: {watch_time}s for keyword: {keyword}",
                extra={
                    "action": "WATCH_VIDEO",
                    "status": "SUCCESS",
                    "keyword": keyword,
                    "watch_time": watch_time,
                },
            )

        if stop_event.is_set():
            return False

        # --------------------------------
        # Return to YouTube Home
        # --------------------------------

        go_to_home(
            driver,
            config,
            stop_event,
            session_logger=session_logger,
        )

        close_mini_player(driver, session_logger=session_logger)

        if session_logger:
            session_logger.info(
                f"YouTube flow completed for keyword: {keyword}",
                extra={
                    "action": "YOUTUBE_FIRST_COMPLETED",
                    "status": "SUCCESS",
                    "keyword": keyword,
                },
            )

    else:

        stats.record_video_not_found()
        try:
            stats.record_keyword_failed(keyword, "youtube", thread_id=str(threading.get_ident()))
        except Exception:
            pass

        print(
            f"[{thread_name}]"
            f"[{selected_browser.upper()}] "
            f"Target channel video not found."
        )

        if session_logger:
            session_logger.warning(
                f"Target channel video not found for keyword: {keyword}",
                extra={
                    "action": "VIDEO_NOT_FOUND",
                    "status": "FAILED",
                    "keyword": keyword,
                },
            )

    return True


def _safe_create_automation_run(run_id, keyword, config, selected_browser):
    """Create DB record without breaking automation if DB is unavailable."""
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
    """Update  DB record without breaking automation if DB is unavailable."""
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
    Supports per-keyword SessionLoggerAdapter with detailed logging
    for both YOUTUBE_FIRST and SEARCH_ENGINE_FIRST flows,
    while preserving robust exception handling, per-keyword stats,
    captcha handling, headless handling, and interrupt handling.
    """

    driver = None
    session_success = True
    current_keyword = None

    # database state: one automation_run per keyword.
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

        logger.warning(
            f"[{thread_name}] Invalid search engine : {selected_search_engine}",
            extra={
                "action": "SESSION_START",
                "status": "FAILED",
                "engine": selected_search_engine,
            },
        )

        stats.record_failure()
        return

    # Browser selected via distribution — record after successful start to handle fallback
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

    logger.info(
        f"[{thread_name}] Selected Browser: {selected_browser} | Engine: {selected_search_engine} | Flow: {flow}",
        extra={
            "action": "SESSION_CONFIG",
            "status": "RUNNING",
            "browser": selected_browser,
            "engine": selected_search_engine,
            "flow": flow,
        },
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

        logger.info(
            f"[{thread_name}][{selected_browser.upper()}] YouTube Session Started | Flow: {flow}",
            extra={
                "action": "SESSION_STARTED",
                "status": "RUNNING",
                "browser": selected_browser,
                "flow": flow,
            },
        )

        # =====================================================
        # START BROWSER — with chrome fallback if requested browser missing/failed
        # =====================================================

        driver = None
        actual_browser = selected_browser
        original_requested = selected_browser
        try:
            driver = setup_browser(
                config,
                selected_browser,
            )
        except Exception as error:
            # Fallback to chrome if any browser fails (binary not found, startup error, etc.)
            if str(selected_browser).lower() != "chrome":
                fallback_browser = "chrome"
                print(
                    f"[{thread_name}] Browser '{selected_browser}' not available ({error}), falling back to '{fallback_browser}'"
                )
                logger.warning(
                    f"[{thread_name}] Browser '{selected_browser}' failed ({error}), falling back to '{fallback_browser}'",
                    extra={
                        "action": "BROWSER_FALLBACK",
                        "status": "RETRYING",
                        "browser": selected_browser,
                        "fallback": fallback_browser,
                    },
                )
                try:
                    driver = setup_browser(config, fallback_browser)
                    actual_browser = fallback_browser
                    # Update selected for rest of session (stats, logs, thread name)
                    selected_browser = fallback_browser
                    print(f"[{thread_name}] Fallback browser '{fallback_browser}' started successfully (requested was '{original_requested}')")
                except Exception as fb_error:
                    session_success = False
                    stats.record_browser_error()
                    print(
                        f"[{thread_name}]"
                        f"[{selected_browser.upper()}] "
                        f"Browser startup failed : {error} | Fallback '{fallback_browser}' also failed: {fb_error}"
                    )
                    logger.error(
                        f"[{thread_name}][{selected_browser.upper()}] Browser startup failed: {error} | Fallback failed: {fb_error}",
                        exc_info=True,
                        extra={
                            "action": "BROWSER_START_FAILED",
                            "status": "FAILED",
                            "browser": selected_browser,
                            "error_message": str(error),
                        },
                    )
                    traceback.print_exc()
                    return
            else:
                session_success = False
                stats.record_browser_error()
                print(
                    f"[{thread_name}]"
                    f"[{selected_browser.upper()}] "
                    f"Browser startup failed : {error}"
                )
                logger.error(
                    f"[{thread_name}][{selected_browser.upper()}] Browser startup failed: {error}",
                    exc_info=True,
                    extra={
                        "action": "BROWSER_START_FAILED",
                        "status": "FAILED",
                        "browser": selected_browser,
                        "error_message": str(error),
                    },
                )
                traceback.print_exc()
                return

        # Record actual browser used (after fallback)
        try:
            stats.record_browser(actual_browser)
        except Exception:
            pass

        if driver is not None:
            _register_driver(driver)

            if actual_browser.lower() != original_requested.lower():
                logger.info(
                    f"[{thread_name}][{actual_browser.upper()}] Browser started: {actual_browser} (fallback from '{original_requested}')",
                    extra={
                        "action": "BROWSER_STARTED",
                        "status": "SUCCESS",
                        "browser": actual_browser,
                        "requested": original_requested,
                    },
                )
            else:
                logger.info(
                    f"[{thread_name}][{actual_browser.upper()}] Browser started: {actual_browser}",
                    extra={
                        "action": "BROWSER_STARTED",
                        "status": "SUCCESS",
                        "browser": actual_browser,
                    },
                )
        else:
            session_success = False
            stats.record_browser_error()
            print(f"[{thread_name}] Browser startup failed: no driver")
            return

        if stop_event.is_set():
            return

        # =====================================================
        # PROCESS KEYWORDS
        # =====================================================

        for keyword in keywords:

            current_keyword = keyword

            if stop_event.is_set():
                try:
                    stats.record_keyword_interrupted(keyword, selected_search_engine, thread_id=str(threading.get_ident()))
                except Exception:
                    pass
                return

            stats.record_keyword()

            # -------------------------------------------------
            # database tracking
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
            # Create per-keyword SessionLoggerAdapter
            # -------------------------------------------------
            # Provides context for all logs within this keyword's flow
            session_logger = SessionLoggerAdapter(
                logger,
                {
                    "keyword": keyword,
                    "engine": "youtube" if flow == "youtube_first" else selected_search_engine,
                    "search_keyword": keyword,
                    "session_id": run_ids[keyword],
                    "app_module": "YOUTUBE",
                    "thread_id": threading.get_ident(),
                    "thread_name": thread_name,
                    "browser": selected_browser,
                    "flow": flow,
                    "target": config.get("youtube", {}).get("targetChannel", ""),
                },
            )

            session_logger.info(
                f"Processing keyword: '{keyword}' | Flow: {flow} | Browser: {selected_browser}",
                extra={
                    "action": "KEYWORD_STARTED",
                    "status": "RUNNING",
                    "keyword": keyword,
                    "flow": flow,
                },
            )

            # -------------------------------------------------
            # Check browser
            # -------------------------------------------------

            if not is_browser_alive(driver, stop_event):

                if stop_event.is_set():
                    # Shutdown — don't count as browser error, count as interrupted
                    try:
                        stats.record_keyword_interrupted(keyword, selected_search_engine, thread_id=str(threading.get_ident()))
                    except Exception:
                        pass
                    return
                session_success = False
                stats.record_browser_error()

                print(
                    f"[{thread_name}]"
                    f"[{selected_browser.upper()}] "
                    f"Browser session disconnected."
                )

                try:
                    session_logger.warning(
                        f"Browser session disconnected for keyword: {keyword}",
                        extra={
                            "action": "BROWSER_HEALTH",
                            "status": "FAILED",
                            "keyword": keyword,
                        },
                    )
                except Exception:
                    pass

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

                session_logger.info(
                    f"[YOUTUBE_FIRST] Processing keyword: {keyword}",
                    extra={
                        "action": "YOUTUBE_FIRST_START",
                        "status": "RUNNING",
                        "keyword": keyword,
                    },
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
                    session_logger=session_logger,
                )

                if not success:

                    session_success = False
                    if not stop_event.is_set():
                        stats.record_keyword_failure()
                        try:
                            stats.record_keyword_failed(keyword, "youtube", thread_id=str(threading.get_ident()))
                        except Exception:
                            pass

                        try:
                            session_logger.warning(
                                f"[YOUTUBE_FIRST] Failed for keyword: {keyword}",
                                extra={
                                    "action": "YOUTUBE_FIRST_FAILED",
                                    "status": "FAILED",
                                    "keyword": keyword,
                                },
                            )
                        except Exception:
                            pass

                        _safe_update_automation_run(
                            run_ids.get(keyword),
                            keyword,
                            "FAILED",
                            retry_count=retry_trackers.get(keyword, {}).get("count", 0),
                            fallback_used=False,
                            search_keyword=keyword,
                        )
                    else:
                        try:
                            stats.record_keyword_interrupted(keyword, "youtube", thread_id=str(threading.get_ident()))
                        except Exception:
                            pass
                        _safe_update_automation_run(
                            run_ids.get(keyword),
                            keyword,
                            "INTERRUPTED",
                            retry_count=retry_trackers.get(keyword, {}).get("count", 0),
                            fallback_used=False,
                            search_keyword=keyword,
                        )

                    if not is_browser_alive(driver, stop_event):

                        if stop_event.is_set():
                            try:
                                stats.record_keyword_interrupted(keyword, "youtube", thread_id=str(threading.get_ident()))
                            except Exception:
                                pass
                            return
                        stats.record_browser_error()
                        try:
                            session_logger.warning(
                                f"Browser died after YOUTUBE_FIRST failure for keyword: {keyword}",
                                extra={
                                    "action": "BROWSER_HEALTH",
                                    "status": "FAILED",
                                    "keyword": keyword,
                                },
                            )
                        except Exception:
                            pass
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

                    session_logger.info(
                        f"[YOUTUBE_FIRST] Completed successfully for keyword: {keyword} (fallback_used={fallback_used})",
                        extra={
                            "action": "YOUTUBE_FIRST_COMPLETED",
                            "status": "SUCCESS",
                            "keyword": keyword,
                            "fallback_used": fallback_used,
                        },
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

            session_logger.info(
                f"[SEARCH_ENGINE_FIRST] Processing keyword: {keyword}",
                extra={
                    "action": "SEARCH_ENGINE_FIRST_START",
                    "status": "RUNNING",
                    "keyword": keyword,
                },
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
                    session_logger.info(
                        f"Stop event set, interrupting keyword: {keyword} on engine: {current_engine}",
                        extra={
                            "action": "SESSION_INTERRUPT",
                            "status": "INTERRUPTED",
                            "keyword": keyword,
                            "engine": current_engine,
                        },
                    )
                    return

                # -------------------------------------------------
                # Update session_logger context to current engine
                # -------------------------------------------------
                try:
                    session_logger.extra["engine"] = current_engine
                except Exception:
                    pass

                # -------------------------------------------------
                # Skip engine if it is not configured
                # -------------------------------------------------

                if current_engine not in search_engines:

                    print(
                        f"[{thread_name}] "
                        f"{current_engine.upper()} is not configured. "
                        f"Skipping."
                    )

                    session_logger.warning(
                        f"{current_engine.upper()} is not configured. Skipping.",
                        extra={
                            "action": "ENGINE_SKIPPED",
                            "status": "SKIPPED",
                            "keyword": keyword,
                            "engine": current_engine,
                        },
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

                session_logger.info(
                    f"Trying Search Engine: {current_engine.upper()} for keyword: {keyword}",
                    extra={
                        "action": "ENGINE_ATTEMPT",
                        "status": "RUNNING",
                        "keyword": keyword,
                        "engine": current_engine,
                    },
                )

                # -------------------------------------------------
                # Clear previous target URL
                # -------------------------------------------------

                driver.target_video_url = None

                # -------------------------------------------------
                # 1. Open Search Engine + Search Keyword
                # -------------------------------------------------

                session_logger.info(
                    f"Opening search engine {current_engine.upper()} and searching keyword: {keyword}",
                    extra={
                        "action": "ENGINE_OPEN",
                        "status": "RUNNING",
                        "keyword": keyword,
                        "engine": current_engine,
                    },
                )

                search_success, _ = retry_operation(

                    lambda: (
                        open_search_engine(
                            driver,
                            current_engine_config,
                            session_logger=session_logger,
                            stop_event=stop_event,
                        ),

                        search_keyword(
                            driver,
                            current_engine_config,
                            keyword,
                            config,
                            stop_event,
                            session_logger=session_logger,
                        ),
                    ),

                    stop_event=stop_event,
                    stats=stats,
                    driver=driver,
                    operation_name=(
                        f"{current_engine.upper()} Search Engine"
                    ),
                    retry_tracker=retry_trackers.get(keyword),
                    session_logger=session_logger,
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

                    session_logger.warning(
                        f"{current_engine.upper()} search failed for keyword: {keyword}. Trying next engine.",
                        extra={
                            "action": "ENGINE_SEARCH_FAILED",
                            "status": "FAILED",
                            "keyword": keyword,
                            "engine": current_engine,
                        },
                    )

                    continue

                if stop_event.is_set():
                    session_logger.info(
                        f"Stop event after search for keyword: {keyword} on engine: {current_engine}",
                        extra={
                            "action": "SESSION_INTERRUPT",
                            "status": "INTERRUPTED",
                            "keyword": keyword,
                            "engine": current_engine,
                        },
                    )
                    return

                print(
                    f"[{thread_name}] "
                    f"{current_engine.upper()} "
                    f"search completed."
                )

                session_logger.info(
                    f"{current_engine.upper()} search completed for keyword: {keyword}",
                    extra={
                        "action": "ENGINE_SEARCH_SUCCESS",
                        "status": "SUCCESS",
                        "keyword": keyword,
                        "engine": current_engine,
                    },
                )

                # -------------------------------------------------
                # Captcha / verification check (all engines, browser-agnostic)
                # -------------------------------------------------

                if stop_event.is_set():
                    return
                try:
                    if is_captcha_page(driver, current_engine, stop_event):
                        print()
                        print(f"[SEARCH ENGINE] Captcha/verification detected on {current_engine.upper()}.")
                        print(f"[SEARCH ENGINE] {current_engine.upper()} unavailable for this keyword.")
                        print("[SEARCH ENGINE] Switching to next search engine...")
                        # Count as expected captcha, not bug
                        try:
                            from utils.exceptions import CaptchaDetectedError
                            raise CaptchaDetectedError(f"Captcha on {current_engine} for {keyword}", engine=current_engine, keyword=keyword)
                        except CaptchaDetectedError as ce:
                            session_logger.warning(
                                f"Captcha on {current_engine} for {keyword}: {ce} [{type(ce).__name__}]",
                                exc_info=False,
                                extra={
                                    "action": "CAPTCHA_DETECTED",
                                    "status": "FAILED",
                                    "keyword": keyword,
                                    "engine": current_engine,
                                },
                            )
                            logger.warning(f"Captcha on {current_engine} for {keyword}: {ce} [{type(ce).__name__}]", exc_info=False)
                            continue
                except CaptchaDetectedError:
                    continue
                except Exception as ce:
                    # Captcha check itself failed — log as unexpected but continue
                    session_logger.warning(
                        f"Captcha check failed for {current_engine}: {ce}",
                        exc_info=False,
                        extra={
                            "action": "CAPTCHA_CHECK_FAILED",
                            "status": "FAILED",
                            "keyword": keyword,
                            "engine": current_engine,
                        },
                    )
                    logger.warning(f"Captcha check failed for {current_engine}: {ce}", exc_info=False)

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

                        session_logger.info(
                            "DUCKDUCKGO promo popup closed.",
                            extra={
                                "action": "POPUP_CLOSED",
                                "status": "SUCCESS",
                                "keyword": keyword,
                                "engine": current_engine,
                            },
                        )

                    except Exception:

                        print(
                            "DUCKDUCKGO promo popup not found."
                        )

                        session_logger.debug(
                            "DUCKDUCKGO promo popup not found.",
                            extra={
                                "action": "POPUP_NOT_FOUND",
                                "status": "SKIPPED",
                                "keyword": keyword,
                                "engine": current_engine,
                            },
                        )

                # -------------------------------------------------
                # 2. Open Videos Tab
                # -------------------------------------------------

                print(
                    f"[{thread_name}] "
                    f"[{current_engine.upper()}] "
                    f"Opening Videos tab..."
                )

                session_logger.info(
                    f"[{current_engine.upper()}] Opening Videos tab for keyword: {keyword}",
                    extra={
                        "action": "OPEN_VIDEO_TAB",
                        "status": "RUNNING",
                        "keyword": keyword,
                        "engine": current_engine,
                    },
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

                    session_logger.warning(
                        f"[{current_engine.upper()}] Failed to open Videos tab for keyword: {keyword}",
                        extra={
                            "action": "OPEN_VIDEO_TAB",
                            "status": "FAILED",
                            "keyword": keyword,
                            "engine": current_engine,
                        },
                    )

                    continue

                if stop_event.is_set():
                    session_logger.info(
                        f"Stop event after opening video tab for keyword: {keyword}",
                        extra={
                            "action": "SESSION_INTERRUPT",
                            "status": "INTERRUPTED",
                            "keyword": keyword,
                            "engine": current_engine,
                        },
                    )
                    return

                session_logger.info(
                    f"[{current_engine.upper()}] Videos tab opened for keyword: {keyword}",
                    extra={
                        "action": "OPEN_VIDEO_TAB",
                        "status": "SUCCESS",
                        "keyword": keyword,
                        "engine": current_engine,
                    },
                )

                # -------------------------------------------------
                # 3. Find Target Video
                # -------------------------------------------------

                print(
                    f"[{thread_name}] "
                    f"[{current_engine.upper()}] "
                    f"Searching Videos results for target "
                    f"channel : {target_channel}"
                )

                session_logger.info(
                    f"[{current_engine.upper()}] Searching Videos results for target channel: {target_channel} | Keyword: {keyword}",
                    extra={
                        "action": "FIND_TARGET_VIDEO",
                        "status": "RUNNING",
                        "keyword": keyword,
                        "engine": current_engine,
                        "target": target_channel,
                    },
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
                    session_logger=session_logger,
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

                    session_logger.warning(
                        f"[{current_engine.upper()}] Error while searching target video for keyword: {keyword}",
                        extra={
                            "action": "FIND_TARGET_VIDEO",
                            "status": "FAILED",
                            "keyword": keyword,
                            "engine": current_engine,
                        },
                    )

                    continue

                if stop_event.is_set():
                    session_logger.info(
                        f"Stop event after finding target video for keyword: {keyword}",
                        extra={
                            "action": "SESSION_INTERRUPT",
                            "status": "INTERRUPTED",
                            "keyword": keyword,
                            "engine": current_engine,
                        },
                    )
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

                        session_logger.warning(
                            f"[{current_engine.upper()}] Target video found but URL was not stored for keyword: {keyword}",
                            extra={
                                "action": "FIND_TARGET_VIDEO",
                                "status": "FAILED",
                                "keyword": keyword,
                                "engine": current_engine,
                            },
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

                    session_logger.info(
                        f"TARGET VIDEO FOUND | Engine: {current_engine.upper()} | Channel: {target_channel} | URL: {target_video_url} | Keyword: {keyword}",
                        extra={
                            "action": "VIDEO_FOUND",
                            "status": "SUCCESS",
                            "keyword": keyword,
                            "engine": current_engine,
                            "url": target_video_url,
                            "target": target_channel,
                        },
                    )

                    stats.record_video_found()
                    try:
                        # For tick/cross summary like main.py
                        stats.record_keyword_success(keyword, current_engine, thread_id=str(threading.get_ident()))
                    except Exception:
                        pass

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

                    session_logger.info(
                        f"Opening target video: {target_video_url} | Keyword: {keyword}",
                        extra={
                            "action": "OPEN_VIDEO",
                            "status": "RUNNING",
                            "keyword": keyword,
                            "engine": current_engine,
                            "url": target_video_url,
                        },
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
                        session_logger.info(
                            f"Stop event after opening target video for keyword: {keyword}",
                            extra={
                                "action": "SESSION_INTERRUPT",
                                "status": "INTERRUPTED",
                                "keyword": keyword,
                                "engine": current_engine,
                            },
                        )
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

                    session_logger.info(
                        f"Watching video for keyword: {keyword} | URL: {target_video_url}",
                        extra={
                            "action": "WATCH_VIDEO",
                            "status": "RUNNING",
                            "keyword": keyword,
                            "engine": current_engine,
                            "url": target_video_url,
                        },
                    )

                    watch_time = watch_video(
                        driver,
                        config,
                        stop_event,
                        session_logger=session_logger,
                        keyword=keyword,
                    )

                    stats.record_watch_time(
                        watch_time
                    )

                    session_logger.info(
                        f"Finished watching video for keyword: {keyword} | Watch time: {watch_time}s",
                        extra={
                            "action": "WATCH_VIDEO",
                            "status": "SUCCESS",
                            "keyword": keyword,
                            "engine": current_engine,
                            "watch_time": watch_time,
                        },
                    )

                    if stop_event.is_set():
                        return

                    # -------------------------------------------------
                    # 6. Return to YouTube Home
                    # -------------------------------------------------

                    session_logger.info(
                        f"Returning to YouTube home for keyword: {keyword}",
                        extra={
                            "action": "GO_HOME",
                            "status": "RUNNING",
                            "keyword": keyword,
                            "engine": current_engine,
                        },
                    )

                    go_to_home(
                        driver,
                        config,
                        stop_event,
                        session_logger=session_logger,
                    )

                    close_mini_player(
                        driver,
                        session_logger=session_logger,
                    )

                    session_logger.info(
                        f"Completed post-watch navigation for keyword: {keyword}",
                        extra={
                            "action": "POST_WATCH_NAVIGATION",
                            "status": "SUCCESS",
                            "keyword": keyword,
                            "engine": current_engine,
                        },
                    )

                    _safe_update_automation_run(
                        run_ids.get(keyword),
                        keyword,
                        "SUCCESS",
                        retry_count=retry_trackers.get(keyword, {}).get("count", 0),
                        fallback_used=False,
                        search_keyword=keyword,
                    )

                    session_logger.info(
                        f"Keyword completed successfully: {keyword} on engine: {current_engine.upper()}",
                        extra={
                            "action": "KEYWORD_COMPLETED",
                            "status": "SUCCESS",
                            "keyword": keyword,
                            "engine": current_engine,
                        },
                    )

                    # -------------------------------------------------
                    # Target found -> stop engine fallback
                    # -------------------------------------------------

                    break

                # -------------------------------------------------
                # Target Video NOT Found on this engine
                # -------------------------------------------------

                else:

                    # Do not count per-engine Not Found here; count once per keyword after all engines exhausted
                    print(
                        f"[{thread_name}] "
                        f"[{current_engine.upper()}] "
                        f"Target channel video not found."
                    )

                    print(
                        f"[{thread_name}] "
                        f"Trying next search engine..."
                    )

                    session_logger.info(
                        f"[{current_engine.upper()}] Target channel video not found for keyword: {keyword}. Trying next engine.",
                        extra={
                            "action": "VIDEO_NOT_FOUND",
                            "status": "RETRYING",
                            "keyword": keyword,
                            "engine": current_engine,
                        },
                    )

            # -------------------------------------------------
            # All Search Engines Exhausted
            # -------------------------------------------------

            if not keyword_completed:

                last_engine_tmp = fallback_engines[-1] if fallback_engines else selected_search_engine
                if stop_event.is_set():
                    try:
                        stats.record_keyword_interrupted(keyword, last_engine_tmp, thread_id=str(threading.get_ident()))
                    except Exception:
                        pass
                    return
                session_success = False

                stats.record_keyword_failure()
                stats.record_video_not_found()
                try:
                    stats.record_keyword_failed(keyword, last_engine_tmp, thread_id=str(threading.get_ident()))
                except Exception:
                    pass

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

                session_logger.warning(
                    f"All search engines exhausted for keyword: {keyword}",
                    extra={
                        "action": "ALL_ENGINES_EXHAUSTED",
                        "status": "FAILED",
                        "keyword": keyword,
                    },
                )

                if not is_browser_alive(driver, stop_event):

                    if stop_event.is_set():
                        try:
                            stats.record_keyword_interrupted(keyword, last_engine_tmp, thread_id=str(threading.get_ident()))
                        except Exception:
                            pass
                        return
                    stats.record_browser_error()

                    try:
                        session_logger.warning(
                            f"Browser died after exhausting engines for keyword: {keyword}",
                            extra={
                                "action": "BROWSER_HEALTH",
                                "status": "FAILED",
                                "keyword": keyword,
                            },
                        )
                    except Exception:
                        pass

                    return

        # =====================================================
        # SESSION COMPLETED
        # =====================================================

        if session_success:

            stats.record_success()
            logger.info(
                f"[{thread_name}][{selected_browser.upper()}] YouTube Session completed successfully (success={session_success})",
                extra={
                    "action": "SESSION_COMPLETED",
                    "status": "SUCCESS",
                    "browser": selected_browser,
                    "flow": flow,
                },
            )

        else:

            stats.record_failure()
            logger.info(
                f"[{thread_name}][{selected_browser.upper()}] YouTube Session completed with failures",
                extra={
                    "action": "SESSION_COMPLETED",
                    "status": "COMPLETED",
                    "browser": selected_browser,
                    "flow": flow,
                },
            )

    # =========================================================
    # UNEXPECTED SESSION ERROR
    # =========================================================

    except (BrowserError, SearchEngineError, CaptchaDetectedError, VideoNotFoundError, YoutubeError, ConfigError) as error:
        # Expected YouTube business failures — graceful
        session_success = False
        if not stop_event.is_set():
            stats.record_failure()
            try:
                stats.record_keyword_failed(current_keyword or (keywords[0] if keywords else "unknown"), selected_search_engine, thread_id=str(threading.get_ident()))
            except Exception:
                pass
            print(f"[{thread_name}][{selected_browser.upper()}] YouTube business failure: {error} [{type(error).__name__}]")
            logger.warning(f"YouTube business failure for {thread_name}: {error} [{type(error).__name__}]", exc_info=False, extra={"action": "SESSION_BUSINESS_FAILURE", "status": "FAILED", "error_message": str(error)})
        else:
            try:
                stats.record_keyword_interrupted(current_keyword or (keywords[0] if keywords else "unknown"), selected_search_engine, thread_id=str(threading.get_ident()))
            except Exception:
                pass
    except UnhandledAutomationError as error:
        session_success = False
        if not stop_event.is_set():
            stats.record_failure()
            print(f"[{thread_name}][{selected_browser.upper()}] YouTube unhandled error: {error} cause={error.cause}")
            logger.error(f"YouTube unhandled error for {thread_name}: {error} cause={error.cause}", exc_info=True, extra={"action": "SESSION_UNHANDLED", "status": "FAILED", "error_message": str(error)})
        else:
            try:
                stats.record_keyword_interrupted(current_keyword or (keywords[0] if keywords else "unknown"), selected_search_engine, thread_id=str(threading.get_ident()))
            except Exception:
                pass
    except Exception as error:
        wrapped = wrap_unexpected(error, f"YouTube session {thread_name}")
        session_success = False
        if not stop_event.is_set():
            stats.record_failure()
            print(f"[{thread_name}][{selected_browser.upper()}] YouTube Session Error (bug): {wrapped}")
            logger.error(f"YouTube Session Error (bug) for {thread_name}: {wrapped}", exc_info=True, extra={"action": "SESSION_BUG", "status": "FAILED", "error_message": str(wrapped)})
            traceback.print_exc()
        else:
            try:
                stats.record_keyword_interrupted(current_keyword or (keywords[0] if keywords else "unknown"), selected_search_engine, thread_id=str(threading.get_ident()))
            except Exception:
                pass

    # =========================================================
    # CLOSE BROWSER
    # =========================================================

    finally:

        if stop_event.is_set() and current_keyword:
            try:
                # Dedup by keyword+thread only (engine ignored) — prevents double-count per worker
                tid = str(threading.get_ident())
                if not any(str(d.get("keyword"))==str(current_keyword) and str(d.get("thread_id", tid))==tid for d in stats.interrupted):
                    if not any(str(d.get("keyword"))==str(current_keyword) and str(d.get("thread_id", tid))==tid for d in stats.failed):
                        if not any(str(d.get("keyword"))==str(current_keyword) and str(d.get("thread_id", tid))==tid for d in stats.success):
                            stats.record_keyword_interrupted(current_keyword, selected_search_engine, thread_id=tid)
            except Exception:
                pass

        if driver:

            try:

                close_browser(driver)

            except Exception as error:

                print(
                    f"[{thread_name}] "
                    f"Browser close error : {error}"
                )
                logger.warning(
                    f"[{thread_name}] Browser close error: {error}",
                    exc_info=False,
                    extra={
                        "action": "BROWSER_CLOSE",
                        "status": "FAILED",
                        "error_message": str(error),
                    },
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
    Robust: timeout join loop for Ctrl+C, stats.print_summary in finally.
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

    interrupted = False
    unexpected_error = None
    result = False
    try:

        for worker in workers:
            worker.start()

        # Use timeout join loop so Ctrl+C (KeyboardInterrupt) is delivered on Windows
        # Plain worker.join() without timeout blocks signal handling
        while any(w.is_alive() for w in workers):
            for w in workers:
                w.join(timeout=0.5)
            if stop_event.is_set():
                break

        result = not stop_event.is_set()

    except KeyboardInterrupt:
        interrupted = True
        # Silence retry logs immediately to prevent NewConnectionError flood
        try:
            from utils.logger import silence_noisy_loggers
            silence_noisy_loggers()
        except Exception:
            pass
        try:
            import logging as _lg
            for _n in ("urllib3","urllib3.connectionpool","selenium","selenium.webdriver.remote.remote_connection"):
                _lg.getLogger(_n).setLevel(_lg.ERROR)
        except Exception:
            pass
        print("\nCtrl+C detected. Stopping automation...")
        logger.info("YouTube automation interrupted by user (Ctrl+C).", extra={"action": "SESSION_INTERRUPT", "status": "INTERRUPTED"})

        stop_event.set()
        # Immediately close browsers to unblock workers stuck in driver.get / wait
        try:
            close_active_drivers(stop_event)
        except Exception:
            pass

        for worker in workers:
            try:
                worker.join(timeout=4)
            except Exception:
                pass

        print("All workers stopped. Closing remaining browsers...")
        try:
            close_active_drivers(stop_event)
        except Exception as e:
            msg = str(e).lower()
            if "newconnectionerror" not in msg and "connection refused" not in msg:
                try:
                    logger.warning(f"close_active_drivers failed during interrupt: {e}", extra={"action": "BROWSER_CLOSE", "status": "FAILED"})
                except Exception:
                    pass

        print("Automation stopped.")
        result = False

    except Exception as error:
        unexpected_error = error
        logger.error(f"Unexpected YouTube automation error: {error}", exc_info=True, extra={"action": "SESSION_BUG", "status": "FAILED", "error_message": str(error)})
        print(f"\nUnexpected Error : {error}")
        stop_event.set()
        for worker in workers:
            try:
                worker.join(timeout=5)
            except Exception:
                pass
        result = False

    finally:
        # Silence before final cleanup to avoid NewConnectionError spam
        try:
            from utils.logger import silence_noisy_loggers
            silence_noisy_loggers()
        except Exception:
            pass
        # Ensure any remaining browsers are closed BEFORE summary — so summary not shown while browser still open
        # First give workers a chance to exit and close their own browsers
        try:
            for w in workers:
                try:
                    w.join(timeout=2)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            close_active_drivers(stop_event)
            # Small pause then second check for drivers that were registered after first close
            import time as _t
            _t.sleep(0.5)
            close_active_drivers(stop_event)
            # Final join to let workers notice driver closure
            for w in workers:
                try:
                    if w.is_alive():
                        w.join(timeout=2)
                except Exception:
                    pass
        except Exception as e:
            msg = str(e).lower()
            if "newconnectionerror" not in msg and "connection refused" not in msg:
                try:
                    logger.warning(f"close_active_drivers in finally failed: {e}", extra={"action": "BROWSER_CLOSE", "status": "FAILED"})
                except Exception:
                    pass
        # Always print summary even on Ctrl+C or error — like main.py (now after browsers closed)
        try:
            stats.print_summary()
            # Consistent Browser Mode line like SEO (main.py) for both flows
            try:
                browser_mode = config.get("browser", {}).get("mode", "unknown") if config else "unknown"
                import logging as _lg
                _lg.getLogger(__name__).info(f"Browser Mode: {str(browser_mode).capitalize()}", extra={"action":"SESSION_FINISHED","status":"SUCCESS"})
                print(f"Browser Mode: {str(browser_mode).capitalize()}")
            except Exception:
                pass
        except Exception as summary_error:
            try:
                logger.error(f"Failed to print YouTube summary: {summary_error}", exc_info=True)
            except Exception:
                pass
            # Fallback console summary
            try:
                print(f"\nYouTube Summary (fallback): sessions={stats.total_sessions} success={stats.successful_sessions} failed={stats.failed_sessions} interrupted={len(stats.interrupted)}")
            except Exception:
                pass

        if interrupted:
            logger.info("YouTube automation ended due to interruption.", extra={"action": "SESSION_INTERRUPT", "status": "INTERRUPTED"})
        elif unexpected_error is not None:
            logger.info("YouTube automation ended due to unexpected error.", extra={"action": "SESSION_BUG", "status": "FAILED"})
        else:
            logger.info(f"YouTube automation ended normally (completed={result}).", extra={"action": "SESSION_FINISHED", "status": "SUCCESS"})

    return result
def start_parallel_sessions_with_queue(keywords, config, search_engines, stats=None):
    """
    compatible queue-based parallel runner.

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
                    extra={"action": "SESSION_BUG", "status": "FAILED", "keyword": keyword, "error_message": str(error)},
                )
            finally:
                job_queue.task_done()

    for _ in range(max_workers):
        workers.append(
            threading.Thread(target=_queued_worker, daemon=True)
        )

    interrupted = False
    unexpected_error = None
    try:
        for worker in workers:
            worker.start()

        while job_queue.unfinished_tasks > 0:
            if stop_event.is_set():
                break
            time.sleep(0.5)

    except KeyboardInterrupt:
        interrupted = True
        logger.info("Ctrl+C detected. Stopping YouTube queue automation...", extra={"action": "SESSION_INTERRUPT", "status": "INTERRUPTED"})
        print("\nCtrl+C detected. Stopping YouTube queue automation...")
        stop_event.set()
        # Do not re-raise — let finally print summary and return stats

    except Exception as error:
        unexpected_error = error
        logger.error(f"Unexpected YouTube queue automation error: {error}", exc_info=True, extra={"action": "SESSION_BUG", "status": "FAILED", "error_message": str(error)})
        print(f"\nUnexpected Error : {error}")
        stop_event.set()

    finally:
        stop_event.set()
        try:
            from utils.logger import silence_noisy_loggers
            silence_noisy_loggers()
        except Exception:
            pass
        # Wait for workers first, then close browsers before summary
        for worker in workers:
            try:
                worker.join(timeout=3)
                if worker.is_alive():
                    logger.warning(f"Worker {worker.name} did not exit cleanly", extra={"action": "SESSION_INTERRUPT", "status": "FAILED"})
            except Exception as e:
                logger.warning(f"Worker join failed: {e}", extra={"action": "SESSION_INTERRUPT", "status": "FAILED"})
        try:
            close_active_drivers(stop_event)
            import time as _t
            _t.sleep(0.5)
            close_active_drivers(stop_event)
        except Exception as e:
            msg = str(e).lower()
            if "newconnectionerror" not in msg and "connection refused" not in msg:
                try:
                    logger.warning(f"close_active_drivers failed: {e}", extra={"action": "BROWSER_CLOSE", "status": "FAILED"})
                except Exception:
                    pass

        # Always print summary even on Ctrl+C or error — matches main.py (after browsers closed)
        try:
            stats.print_summary()
        except Exception as summary_error:
            logger.error(f"Failed to print YouTube queue summary: {summary_error}", exc_info=True)
            try:
                print(f"\nYouTube Queue Summary (fallback): sessions={stats.total_sessions} success={stats.successful_sessions} failed={stats.failed_sessions} interrupted={len(stats.interrupted)}")
            except Exception:
                pass

        if interrupted:
            logger.info("YouTube queue automation ended due to interruption.", extra={"action": "SESSION_INTERRUPT", "status": "INTERRUPTED"})
        elif unexpected_error is not None:
            logger.info("YouTube queue automation ended due to unexpected error.", extra={"action": "SESSION_BUG", "status": "FAILED"})
        else:
            logger.info("YouTube queue automation ended normally.", extra={"action": "SESSION_FINISHED", "status": "SUCCESS"})

    return stats