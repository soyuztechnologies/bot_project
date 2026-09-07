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

def _short_err(e, max_len=250):
    """Truncate long WebDriver stacktraces to first line for cleaner console (keeps full in DB via error_message)."""
    try:
        s = str(e).splitlines()[0][:max_len]
        return s
    except Exception:
        return str(e)[:max_len]

from browser.browser import setup_browser, close_browser
from browser.browser_selector import select_browser
from automation.search_engine import (
    open_search_engine,
    search_keyword,
    retry_operation_search, # Import the new retry wrapper
    is_captcha_page,
)
from automation.website import visit_website
from utils.database import create_automation_run, update_automation_run
from utils.exceptions import (
    BrowserBinaryNotFoundError,
    BrowserDiedError,
    BrowserError,
    BrowserStartupError,
    CaptchaDetectedError,
    ConfigError,
    EngineConfigError,
    EngineOpenError,
    InvalidLocatorError,
    NavigationError,
    SearchEngineError,
    SearchFailedError,
    SeoBotError,
    TargetNotFoundError,
    UnhandledAutomationError,
    UnsupportedBrowserError,
    wrap_unexpected,
)

# ---------------------------------------------------------
# Session Logger Adapter
# ---------------------------------------------------------
# Keeps session-specific fields such as session_id/run_id
# while also preserving per-log fields such as action,
# status, url and error_message.
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

logger = logging.getLogger(__name__)

_ACTIVE_DRIVERS = set()
_ACTIVE_DRIVERS_LOCK = threading.Lock()
_STATS_LOCK = threading.Lock()


def _is_browser_alive(driver, stop_event=None) -> bool:
    if stop_event is not None:
        try:
            if stop_event.is_set():
                return False
        except Exception:
            pass
    if not driver:
        return False
    try:
        _ = driver.current_url
        return True
    except Exception as e:
        # Suppress NewConnectionError spam on shutdown
        msg = str(e).lower()
        if "newconnectionerror" in msg or "connection refused" in msg or "connectionreseterror" in msg:
            return False
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
    if not _is_browser_alive(driver, stop_event):
        if stop_event and stop_event.is_set():
            return False
        if session_logger:
            try:
                session_logger.warning("Browser not alive before driver.get", extra={'action': 'DRIVER_GET', 'status': 'FAILED'})
            except Exception:
                pass
        return False
    try:
        driver.set_page_load_timeout(timeout)
    except Exception:
        pass
    try:
        driver.get(url)
        return True
    except Exception as e:
        if stop_event and stop_event.is_set():
            return False
        msg = str(e).lower()
        if "newconnectionerror" in msg or "connection refused" in msg:
            return False
        if session_logger:
            try:
                session_logger.warning(f"driver.get failed for {url}: {e}", extra={'action': 'DRIVER_GET', 'status': 'FAILED', 'error_message': str(e), 'url': url})
            except Exception:
                pass
        return False


def _register_driver(driver):
    with _ACTIVE_DRIVERS_LOCK:
        _ACTIVE_DRIVERS.add(driver)


def _unregister_driver(driver):
    with _ACTIVE_DRIVERS_LOCK:
        _ACTIVE_DRIVERS.discard(driver)


_CLOSED_DRIVER_IDS = set()
_CLOSED_DRIVER_IDS_LOCK = threading.Lock()

def _kill_orphaned_browser_profiles():
    """Best-effort sweep for any remaining browser_profiles processes (orphaned msedge/chrome)."""
    try:
        import psutil, os
        # Find browser_profiles root from drivers or cwd
        roots = set()
        with _ACTIVE_DRIVERS_LOCK:
            for d in list(_ACTIVE_DRIVERS):
                try:
                    p = getattr(d, "_seo_profile_dir", None)
                    if p:
                        roots.add(os.path.normpath(str(p)).replace("\\", "/").lower())
                except Exception:
                    pass
        # Also check filesystem browser_profiles dir if exists
        try:
            from pathlib import Path
            bp = Path.cwd() / "browser_profiles"
            if bp.exists():
                # Any chrome/msedge with browser_profiles in cmdline is ours
                probe = str(bp).replace("\\", "/").lower()
                if probe not in roots:
                    roots.add(probe)
        except Exception:
            pass
        if not roots:
            return
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmdline = proc.info.get("cmdline")
                if not cmdline:
                    continue
                try:
                    cmd_joined = " ".join(cmdline).replace("\\", "/").lower()
                except Exception:
                    continue
                for root in roots:
                    if root in cmd_joined:
                        # Check name is chrome/msedge/firefox etc to avoid killing unrelated python
                        try:
                            from browser.browser import _kill_process_tree_psutil
                            _kill_process_tree_psutil(proc.info["pid"])
                        except Exception:
                            try:
                                proc.kill()
                            except Exception:
                                pass
                        break
            except Exception:
                continue
    except ImportError:
        pass
    except Exception:
        pass


def close_active_drivers(stop_event=None):
    """Close every browser that is currently running — suppresses NewConnectionError spam and ensures no browser remains after Ctrl+C."""
    # Silence urllib3 retry warnings before quitting drivers (prevents flood on Ctrl+C)
    try:
        from utils.logger import silence_noisy_loggers
        silence_noisy_loggers()
    except Exception:
        pass
    # Also directly silence at ERROR level as fallback
    try:
        import logging as _logging
        for _name in ("urllib3", "urllib3.connectionpool", "selenium", "selenium.webdriver.remote.remote_connection"):
            _logging.getLogger(_name).setLevel(_logging.ERROR)
    except Exception:
        pass

    with _ACTIVE_DRIVERS_LOCK:
        drivers = list(_ACTIVE_DRIVERS)

    if not drivers:
        # Still sweep for orphaned profiles (edge may have detached from driver list)
        try:
            _kill_orphaned_browser_profiles()
        except Exception:
            pass
        return

    # Deduplicate — retry only if previous close succeeded (failed stays for retry)
    to_close = []
    for d in drivers:
        try:
            did = id(d)
            with _CLOSED_DRIVER_IDS_LOCK:
                if did in _CLOSED_DRIVER_IDS:
                    continue
            to_close.append(d)
        except Exception:
            to_close.append(d)

    if not to_close:
        return

    for driver in to_close:
        try:
            ok = close_browser(driver, timeout=4.0)
            if ok:
                try:
                    with _CLOSED_DRIVER_IDS_LOCK:
                        _CLOSED_DRIVER_IDS.add(id(driver))
                except Exception:
                    pass
                try:
                    with _ACTIVE_DRIVERS_LOCK:
                        _ACTIVE_DRIVERS.discard(driver)
                except Exception:
                    pass
            else:
                # Keep in active set for next retry — don't mark as closed
                # Try extra profile kill as fallback
                try:
                    from browser.browser import _kill_browsers_by_profile
                    profile = getattr(driver, "_seo_profile_dir", None)
                    if profile:
                        _kill_browsers_by_profile(str(profile))
                except Exception:
                    pass
        except Exception:
            # Keep for retry
            pass
    # Also sweep orphans
    try:
        _kill_orphaned_browser_profiles()
    except Exception:
        pass


def _click_internal_links(driver, config, stop_event, session_logger):
    """Finds and navigates to internal links on the website. Best-effort, never fails session."""
    try:
        if stop_event and stop_event.is_set():
            return
        internal_links_config = config.get("website", {}).get("internal_links", {})

        if not internal_links_config.get("enabled"):
            return

        if stop_event.is_set():
            return
        if not _is_browser_alive(driver, stop_event):
            if stop_event.is_set():
                return
            try:
                session_logger.warning("Skipping internal links - browser not alive", extra={'action': 'INTERNAL_LINK_SEARCH', 'status': 'SKIPPED'})
            except Exception:
                pass
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
            if not _is_browser_alive(driver, stop_event):
                return
            try:
                elements = driver.find_elements(By.XPATH, selector)
                for element in elements:
                    if stop_event.is_set():
                        return
                    try:
                        href = element.get_attribute("href")
                    except Exception as e:
                        msg = str(e).lower()
                        if "newconnectionerror" in msg or "connection refused" in msg:
                            return
                        continue
                    # Ensure the link is valid and internal
                    if href and target_domain in href:
                        link_urls.add(href)
            except Exception as e:
                if stop_event.is_set():
                    return
                msg = str(e).lower()
                if "newconnectionerror" in msg or "connection refused" in msg:
                    return
                try:
                    session_logger.warning(
                        f"Error finding links with selector '{selector}': {e}",
                        extra={'action': 'INTERNAL_LINK_SEARCH', 'status': 'FAILED'}
                    )
                except Exception:
                    pass
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
            if not _is_browser_alive(driver, stop_event):
                if stop_event.is_set():
                    return
                try:
                    session_logger.warning("Browser died during internal link visits", extra={'action': 'INTERNAL_LINK_VISIT', 'status': 'FAILED'})
                except Exception:
                    pass
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
                if stop_event and stop_event.is_set():
                    return
                msg = str(e).lower()
                if "newconnectionerror" not in msg and "connection refused" not in msg:
                    try:
                        session_logger.warning(f"Error visiting internal link {url}: {e} (continuing)", extra={'action': 'INTERNAL_LINK_VISIT', 'status': 'FAILED', 'url': url, 'error_message': str(e)})
                    except Exception:
                        pass
                if not _is_browser_alive(driver, stop_event):
                    return
                continue
    except Exception as e:
        # Outer catch - internal links must never kill session
        try:
            session_logger.warning(f"Internal links flow failed but session continues: {e}", extra={'action': 'INTERNAL_LINK_SEARCH', 'status': 'FAILED', 'error_message': str(e)})
        except Exception:
            pass


def _get_fallback_engine_order(config, search_engines, all_engine_names, initial_engine_name, initial_engine):
    """
    Build ordered fallback list: start with assigned engine, then remaining engines shuffled.
    Future-proof: works with any browsers/distribution and any search engines added later.
    Filters missing engines and case-insensitive matches.
    """
    try:
        # Use provided search_engines dict if available
        if search_engines is not None:
            if all_engine_names is None:
                all_engine_names = list(search_engines.keys())
            ordered_names = [initial_engine_name] + [n for n in all_engine_names if str(n).lower() != str(initial_engine_name).lower()]
            if len(ordered_names) > 1:
                remaining = ordered_names[1:]
                random.shuffle(remaining)
                ordered_names = [ordered_names[0]] + remaining
            fallback = []
            for n in ordered_names:
                eng = search_engines.get(n)
                if eng is None:
                    # case-insensitive lookup
                    for k, v in search_engines.items():
                        if str(k).lower() == str(n).lower():
                            eng = v
                            n = k
                            break
                if eng is not None:
                    fallback.append((n, eng))
            if fallback:
                return fallback
        # Fallback: derive from config search.engines list
        cfg_engines = config.get("search", {}).get("engines", [])
        if isinstance(cfg_engines, list) and cfg_engines:
            # Build order with initial first
            ordered = [initial_engine_name] + [e for e in cfg_engines if str(e).lower() != str(initial_engine_name).lower()]
            # Deduplicate case-insensitive keep first
            seen = set()
            uniq_ordered = []
            for e in ordered:
                low = str(e).lower()
                if low not in seen:
                    seen.add(low)
                    uniq_ordered.append(e)
            # Map to engine dicts if search_engines available else use initial for fallback attempts that will navigate via direct URL
            fallback = []
            for n in uniq_ordered:
                eng = None
                if search_engines is not None:
                    eng = search_engines.get(n)
                    if eng is None:
                        for k, v in search_engines.items():
                            if str(k).lower() == str(n).lower():
                                eng = v
                                n = k
                                break
                if eng is None:
                    # If no dict, reuse initial engine dict as placeholder (open_search_engine will fail but we still try captcha detection loop)
                    # Better to skip if no dict
                    if n == initial_engine_name:
                        eng = initial_engine
                    else:
                        continue
                fallback.append((n, eng))
            if fallback:
                return fallback
    except Exception:
        pass
    return [(initial_engine_name, initial_engine)]


def run_session(keyword, config, engine_name, engine, stop_event, stats, search_engines=None, all_engine_names=None):
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

    selected_browser = select_browser(config).lower()

    # Create a LoggerAdapter that will add session-specific context to all logs.
    session_logger = SessionLoggerAdapter(
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
        # 1) Browser startup - with chrome fallback if requested browser missing/failed
        # -------------------------------------------------
        original_requested_browser = selected_browser
        try:
            driver = setup_browser(config, selected_browser)
            _register_driver(driver)
            if selected_browser.lower() != original_requested_browser.lower():
                session_logger.info(f"Browser started: {selected_browser} (fallback from '{original_requested_browser}')", extra={'action': 'BROWSER_STARTED', 'status': 'SUCCESS'})
            else:
                session_logger.info(f"Browser started: {selected_browser}", extra={'action': 'BROWSER_STARTED', 'status': 'SUCCESS'})
        except Exception as e:
            # Fallback to chrome if any browser fails (binary not found, startup error)
            if str(selected_browser).lower() != "chrome":
                fallback_browser = "chrome"
                try:
                    session_logger.warning(f"Browser '{selected_browser}' not available ({e}), falling back to '{fallback_browser}'", extra={'action': 'BROWSER_FALLBACK', 'status': 'RETRYING', 'error_message': str(e)})
                except Exception:
                    pass
                try:
                    driver = setup_browser(config, fallback_browser)
                    _register_driver(driver)
                    selected_browser = fallback_browser
                    try:
                        session_logger.info(f"Browser fallback '{fallback_browser}' started (requested was '{original_requested_browser}')", extra={'action': 'BROWSER_STARTED', 'status': 'SUCCESS', 'browser': fallback_browser})
                    except Exception:
                        pass
                except Exception as fb_e:
                    session_logger.error(f"Browser startup failed ({original_requested_browser}): {e} | Fallback '{fallback_browser}' also failed: {fb_e}", exc_info=True, extra={'action': 'BROWSER_START_FAILED', 'status': 'FAILED', 'error_message': str(fb_e)})
                    with _STATS_LOCK:
                        if not any(d.get('keyword') == original_keyword for d in stats["failed"]):
                            stats["failed"].append({"keyword": original_keyword, "engine": engine_name})
                    failure_count = 1
                    status = "FAILED"
                    return
            else:
                session_logger.error(f"Browser startup failed ({selected_browser}): {e}", exc_info=True, extra={'action': 'BROWSER_START_FAILED', 'status': 'FAILED', 'error_message': str(e)})
                with _STATS_LOCK:
                    if not any(d.get('keyword') == original_keyword for d in stats["failed"]):
                        stats["failed"].append({"keyword": original_keyword, "engine": engine_name})
                failure_count = 1
                status = "FAILED"
                return

        if stop_event.is_set() or not _is_browser_alive(driver, stop_event):
            status = "INTERRUPTED" if stop_event.is_set() else "FAILED"
            if not _is_browser_alive(driver, stop_event):
                if stop_event.is_set():
                    status = "INTERRUPTED"
                    return
                try:
                    session_logger.warning("Browser died immediately after startup", extra={'action': 'BROWSER_HEALTH', 'status': 'FAILED'})
                except Exception:
                    pass
                with _STATS_LOCK:
                    # avoid duplicate
                    if not any(d.get('keyword') == original_keyword for d in stats["failed"]):
                        stats["failed"].append({"keyword": original_keyword, "engine": engine_name})
                failure_count = 1
                status = "FAILED"
            return

        # -------------------------------------------------
        # 2-5) Engine fallback loop with CAPTCHA handling
        # Handles: open -> search -> find across all engines (browser-agnostic)
        # If CAPTCHA on any engine, switch to next engine with same keyword
        # After all engines exhausted with original keyword, try fallback keyword across all engines
        # If still CAPTCHA on all, count as FAILED/not found and close browser cleanly
        # -------------------------------------------------
        fallback_order = _get_fallback_engine_order(config, search_engines, all_engine_names, engine_name, engine)
        session_logger.info(f"Engine fallback order for '{original_keyword}': {[n for n,_ in fallback_order]} (browser={selected_browser})", extra={'action': 'ENGINE_FALLBACK_ORDER', 'status': 'RUNNING', 'engine': engine_name})

        found = False
        successful_engine_name = None
        successful_engine = None
        captcha_engines = set()
        engines_tried = []

        # Helper to check captcha with logging
        def _is_captcha_and_log(curr_engine_name):
            if stop_event.is_set():
                return False
            try:
                if is_captcha_page(driver, curr_engine_name, stop_event):
                    if stop_event.is_set():
                        return False
                    try:
                        session_logger.warning(f"Captcha detected on {curr_engine_name} for '{current_search_keyword}' (browser={selected_browser})", extra={'action': 'CAPTCHA_DETECTED', 'status': 'FAILED', 'engine': curr_engine_name})
                    except Exception:
                        pass
                    captcha_engines.add(curr_engine_name)
                    return True
            except Exception as ce:
                if stop_event.is_set():
                    return False
                msg = str(ce).lower()
                if "newconnectionerror" in msg or "connection refused" in msg:
                    return False
                try:
                    session_logger.warning(f"Captcha check failed on {curr_engine_name}: {ce}", extra={'action': 'CAPTCHA_CHECK_FAILED', 'status': 'FAILED', 'engine': curr_engine_name})
                except Exception:
                    pass
            return False

        # -------------------------------------------------
        # Try original keyword across engines
        # -------------------------------------------------
        for idx, (curr_engine_name, curr_engine) in enumerate(fallback_order):
            if stop_event.is_set():
                status = "INTERRUPTED"
                return
            if not _is_browser_alive(driver, stop_event):
                if stop_event.is_set():
                    status = "INTERRUPTED"
                    return
                try:
                    session_logger.warning("Browser died before engine attempt", extra={'action': 'BROWSER_HEALTH', 'status': 'FAILED', 'engine': curr_engine_name})
                except Exception:
                    pass
                with _STATS_LOCK:
                    if not any(d.get('keyword') == original_keyword for d in stats["failed"]):
                        stats["failed"].append({"keyword": original_keyword, "engine": engine_name})
                failure_count = 1
                status = "FAILED"
                return

            engines_tried.append(curr_engine_name)
            try:
                session_logger.extra['engine'] = curr_engine_name
            except Exception:
                pass
            # Update engine_name for logging context but keep original for final stats fallback
            current_engine_name = curr_engine_name
            current_engine = curr_engine

            session_logger.info(f"Attempting engine {current_engine_name} ({idx+1}/{len(fallback_order)}) for '{current_search_keyword}'", extra={'action': 'ENGINE_ATTEMPT', 'status': 'RUNNING', 'engine': current_engine_name})

            # Open search engine
            try:
                open_search_engine(driver, current_engine, session_logger, stop_event)
                session_logger.info(f"Search engine opened: {current_engine_name}", extra={'action': 'ENGINE_OPEN', 'status': 'SUCCESS', 'engine': current_engine_name})
            except Exception as e:
                if stop_event.is_set():
                    status = "INTERRUPTED"
                    return
                msg = str(e).lower()
                if "newconnectionerror" not in msg and "connection refused" not in msg:
                    try:
                        session_logger.warning(f"Open search engine failed ({current_engine_name}): {_short_err(e)}", extra={'action': 'ENGINE_OPEN', 'status': 'FAILED', 'engine': current_engine_name, 'error_message': str(e)})
                    except Exception:
                        pass
                if not _is_browser_alive(driver, stop_event):
                    if stop_event.is_set():
                        status = "INTERRUPTED"
                        return
                    try:
                        session_logger.error("Browser died during engine open", extra={'action': 'ENGINE_OPEN', 'status': 'FAILED', 'engine': current_engine_name})
                    except Exception:
                        pass
                    with _STATS_LOCK:
                        if not any(d.get('keyword') == original_keyword for d in stats["failed"]):
                            stats["failed"].append({"keyword": original_keyword, "engine": engine_name})
                    failure_count = 1
                    status = "FAILED"
                    return
                # Try next engine
                continue

            if stop_event.is_set():
                status = "INTERRUPTED"
                return
            if not _is_browser_alive(driver, stop_event):
                if stop_event.is_set():
                    status = "INTERRUPTED"
                    return
                try:
                    session_logger.warning("Browser not alive before search", extra={'action': 'BROWSER_HEALTH', 'status': 'FAILED', 'engine': current_engine_name})
                except Exception:
                    pass
                with _STATS_LOCK:
                    if not any(d.get('keyword') == original_keyword for d in stats["failed"]):
                        stats["failed"].append({"keyword": original_keyword, "engine": engine_name})
                failure_count = 1
                status = "FAILED"
                return

            # CAPTCHA after open
            if _is_captcha_and_log(current_engine_name):
                # Small pause before switching engine to avoid rapid hammering
                try:
                    time.sleep(random.uniform(1, 2))
                except Exception:
                    pass
                continue

            # Search keyword
            try:
                search_keyword(driver, current_engine, current_search_keyword, config, stop_event, session_logger)
            except Exception as e:
                if stop_event.is_set():
                    status = "INTERRUPTED"
                    return
                msg = str(e).lower()
                if "newconnectionerror" not in msg and "connection refused" not in msg:
                    try:
                        session_logger.warning(f"Search failed for '{current_search_keyword}' on {current_engine_name}: {e}", extra={'action': 'KEYWORD_SEARCH', 'status': 'FAILED', 'engine': current_engine_name, 'error_message': str(e)})
                    except Exception:
                        pass
                if not _is_browser_alive(driver, stop_event):
                    if stop_event.is_set():
                        status = "INTERRUPTED"
                        return
                    with _STATS_LOCK:
                        if not any(d.get('keyword') == original_keyword for d in stats["failed"]):
                            stats["failed"].append({"keyword": original_keyword, "engine": engine_name})
                    failure_count = 1
                    status = "FAILED"
                    return
                continue

            if stop_event.is_set():
                status = "INTERRUPTED"
                return
            if not _is_browser_alive(driver, stop_event):
                if stop_event.is_set():
                    status = "INTERRUPTED"
                    return
                try:
                    session_logger.warning("Browser died after search", extra={'action': 'BROWSER_HEALTH', 'status': 'FAILED', 'engine': current_engine_name})
                except Exception:
                    pass
                with _STATS_LOCK:
                    if not any(d.get('keyword') == original_keyword for d in stats["failed"]):
                        stats["failed"].append({"keyword": original_keyword, "engine": engine_name})
                failure_count = 1
                status = "FAILED"
                return

            # CAPTCHA after search
            if _is_captcha_and_log(current_engine_name):
                try:
                    time.sleep(random.uniform(1, 2))
                except Exception:
                    pass
                continue

            # Find target website
            found_tmp = False
            try:
                found_tmp, tmp_retry = retry_operation_search(driver, current_engine, target, config["search"].get("maxPages", 20), stop_event, session_logger)
                retry_count += tmp_retry
            except Exception as e:
                if stop_event.is_set():
                    status = "INTERRUPTED"
                    return
                msg = str(e).lower()
                if "newconnectionerror" not in msg and "connection refused" not in msg:
                    try:
                        session_logger.warning(f"Find target crashed on {current_engine_name}: {e}", extra={'action': 'WEBSITE_SEARCH', 'status': 'FAILED', 'engine': current_engine_name, 'error_message': str(e)})
                    except Exception:
                        pass
                found_tmp = False

            # CAPTCHA during/after website search (engine may have switched to captcha during pagination)
            if not found_tmp and _is_captcha_and_log(current_engine_name):
                continue

            if found_tmp:
                found = True
                successful_engine_name = current_engine_name
                successful_engine = current_engine
                engine_name = successful_engine_name
                engine = successful_engine
                try:
                    session_logger.extra['engine'] = engine_name
                except Exception:
                    pass
                session_logger.info(f"Website found on {engine_name} for '{current_search_keyword}'", extra={'action': 'WEBSITE_FOUND', 'status': 'SUCCESS', 'engine': engine_name})
                break
            else:
                # Per-engine fallback: if not found with original keyword, immediately try "Anubhav Training" on SAME engine before switching
                if stop_event.is_set():
                    status = "INTERRUPTED"
                    return
                extra_keyword = config.get("website", {}).get("extra_keyword", "").strip()
                if extra_keyword and extra_keyword.lower() not in original_keyword.lower():
                    if stop_event.is_set():
                        status = "INTERRUPTED"
                        return
                    fallback_keyword = f"{original_keyword} {extra_keyword}"
                    # Don't log fallback if interrupted
                    if stop_event.is_set():
                        status = "INTERRUPTED"
                        return
                    try:
                        session_logger.warning(f"Website not found on {current_engine_name} with '{current_search_keyword}'. Immediately retrying fallback keyword '{fallback_keyword}' on SAME engine", extra={'action': 'FALLBACK_SAME_ENGINE', 'status': 'RUNNING', 'engine': current_engine_name})
                    except Exception:
                        pass
                    # Mark fallback as attempted for DB/stats
                    fallback_used = True
                    # Try fallback on same engine (keep current_search_keyword as original until fallback succeeds)
                    fallback_found_on_same_engine = False
                    try:
                        # Re-open engine homepage to get clean search box (fixes duplication like "kw kw anubhav")
                        try:
                            open_search_engine(driver, current_engine, session_logger, stop_event)
                        except Exception as e:
                            session_logger.warning(f"Fallback open failed on {current_engine_name}: {e}", extra={'action': 'ENGINE_OPEN', 'status': 'FAILED', 'engine': current_engine_name})
                            if not _is_browser_alive(driver):
                                with _STATS_LOCK:
                                    if not any(d.get('keyword') == original_keyword for d in stats["failed"]):
                                        stats["failed"].append({"keyword": original_keyword, "engine": engine_name})
                                failure_count = 1
                                status = "FAILED"
                                return
                        else:
                            if _is_captcha_and_log(current_engine_name):
                                session_logger.warning(f"Captcha on fallback open for {current_engine_name}, skipping fallback on this engine", extra={'action': 'CAPTCHA_DETECTED', 'status': 'FAILED', 'engine': current_engine_name})
                            else:
                                try:
                                    search_keyword(driver, current_engine, fallback_keyword, config, stop_event, session_logger)
                                except Exception as e:
                                    if stop_event.is_set():
                                        status = "INTERRUPTED"
                                        return
                                    msg = str(e).lower()
                                    if "newconnectionerror" not in msg and "connection refused" not in msg:
                                        try:
                                            session_logger.warning(f"Fallback search failed on {current_engine_name}: {e}", extra={'action': 'FALLBACK_SEARCH_STARTED', 'status': 'FAILED', 'engine': current_engine_name})
                                        except Exception:
                                            pass
                                else:
                                    if _is_captcha_and_log(current_engine_name):
                                        if stop_event.is_set():
                                            status = "INTERRUPTED"
                                            return
                                        try:
                                            session_logger.warning(f"Captcha after fallback search on {current_engine_name}", extra={'action': 'CAPTCHA_DETECTED', 'status': 'FAILED', 'engine': current_engine_name})
                                        except Exception:
                                            pass
                                    else:
                                        try:
                                            found_fallback_same, tmp_retry_same = retry_operation_search(driver, current_engine, target, config["search"].get("maxPages", 20), stop_event, session_logger)
                                            retry_count += tmp_retry_same
                                        except Exception as e:
                                            if stop_event.is_set():
                                                status = "INTERRUPTED"
                                                return
                                            msg = str(e).lower()
                                            if "newconnectionerror" not in msg and "connection refused" not in msg:
                                                try:
                                                    session_logger.warning(f"Fallback find failed on {current_engine_name}: {e}", extra={'action': 'WEBSITE_SEARCH', 'status': 'FAILED', 'engine': current_engine_name})
                                                except Exception:
                                                    pass
                                            found_fallback_same = False
                                        if not found_fallback_same and _is_captcha_and_log(current_engine_name):
                                            pass
                                        elif found_fallback_same:
                                            fallback_found_on_same_engine = True
                                            fallback_used = True
                                            current_search_keyword = fallback_keyword
                                            try:
                                                session_logger.extra['search_keyword'] = current_search_keyword
                                            except Exception:
                                                pass
                                            found = True
                                            successful_engine_name = current_engine_name
                                            successful_engine = current_engine
                                            engine_name = successful_engine_name
                                            engine = successful_engine
                                            try:
                                                session_logger.extra['engine'] = engine_name
                                            except Exception:
                                                pass
                                            session_logger.info(f"Website found via per-engine fallback on {engine_name} for '{current_search_keyword}'", extra={'action': 'WEBSITE_FOUND', 'status': 'SUCCESS', 'engine': engine_name})
                                            break
                    except Exception as e:
                        if stop_event.is_set():
                            status = "INTERRUPTED"
                            return
                        msg = str(e).lower()
                        if "newconnectionerror" not in msg and "connection refused" not in msg:
                            try:
                                session_logger.warning(f"Per-engine fallback flow failed on {current_engine_name}: {e}", extra={'action': 'FALLBACK_SAME_ENGINE', 'status': 'FAILED', 'engine': current_engine_name})
                            except Exception:
                                pass
                    if fallback_found_on_same_engine:
                        break
                    # Mark fallback as used even if this engine's fallback failed, to prevent duplicate outer fallback? Keep False to allow fallback on next engine's same logic
                    # Do not set fallback_used to True on failure — allow next engine to also try same fallback
                    # Continue to next engine with original keyword (fallback will be retried per-engine)
                if stop_event.is_set():
                    status = "INTERRUPTED"
                    return
                try:
                    session_logger.info(f"Website not found on {current_engine_name} for '{current_search_keyword}', trying next engine", extra={'action': 'WEBSITE_NOT_FOUND', 'status': 'RETRYING', 'engine': current_engine_name})
                except Exception:
                    pass
                continue

        # Note: Per-engine fallback with "Anubhav Training" already handled inside the engine loop (immediate retry on same engine if not found).
        # No additional cross-engine fallback needed here to avoid duplicate searches.

        if stop_event.is_set():
            status = "INTERRUPTED"
            return

        # -------------------------------------------------
        # 6) Result handling - website found vs not found (including captcha-exhausted)
        # -------------------------------------------------
        if stop_event.is_set():
            status = "INTERRUPTED"
            return
        if found:
            # If interrupted while visiting, don't count as success
            if stop_event.is_set():
                status = "INTERRUPTED"
                return
            try:
                cur_url = driver.current_url if _is_browser_alive(driver, stop_event) else ""
            except Exception:
                cur_url = ""
            # Log which engine succeeded and if captcha was encountered earlier
            if captcha_engines:
                session_logger.info(f"Website found for '{current_search_keyword}' on {engine_name} after captcha on {sorted(captcha_engines)}", extra={'action': 'WEBSITE_FOUND', 'status': 'SUCCESS', 'url': cur_url, 'engine': engine_name})
            else:
                session_logger.info(f"Website found for '{current_search_keyword}' on {engine_name}.", extra={'action': 'WEBSITE_FOUND', 'status': 'SUCCESS', 'url': cur_url, 'engine': engine_name})
            # Visit website - best effort, must not fail session (check stop before each)
            if stop_event.is_set():
                status = "INTERRUPTED"
                return
            try:
                visit_website(driver, config, stop_event, session_logger)
            except Exception as e:
                if stop_event.is_set():
                    status = "INTERRUPTED"
                    return
                msg = str(e).lower()
                if "newconnectionerror" not in msg and "connection refused" not in msg:
                    try:
                        session_logger.warning(f"visit_website best-effort failed: {e}", extra={'action': 'WEBSITE_VISIT', 'status': 'FAILED', 'error_message': str(e)})
                    except Exception:
                        pass
            if stop_event.is_set():
                status = "INTERRUPTED"
                return
            # Internal links - best effort
            try:
                _click_internal_links(driver, config, stop_event, session_logger)
            except Exception as e:
                if stop_event.is_set():
                    status = "INTERRUPTED"
                    return
                msg = str(e).lower()
                if "newconnectionerror" not in msg and "connection refused" not in msg:
                    try:
                        session_logger.warning(f"Internal links best-effort failed: {e}", extra={'action': 'INTERNAL_LINK_SEARCH', 'status': 'FAILED', 'error_message': str(e)})
                    except Exception:
                        pass
            if stop_event.is_set():
                status = "INTERRUPTED"
                return
            with _STATS_LOCK:
                # Don't count as success if interrupted during visit
                if stop_event.is_set():
                    if not any(d.get('keyword') == original_keyword for d in stats.get("interrupted", [])):
                        stats["interrupted"].append({"keyword": original_keyword, "engine": engine_name})
                else:
                    stats["success"].append({"keyword": original_keyword, "engine": engine_name})
                    success_count = 1
                    status = "SUCCESS"
                    return
            # If interrupted, fall through to interrupted handling
            if stop_event.is_set():
                status = "INTERRUPTED"
                return
            success_count = 1
            status = "SUCCESS"
        else:
            # If interrupted while not found, don't count as failed
            if stop_event.is_set():
                status = "INTERRUPTED"
                return
            # Handle captcha-exhausted vs normal not found vs all engines tried
            if captcha_engines and len(captcha_engines) >= len(fallback_order):
                try:
                    session_logger.warning(f"Captcha on all engines {sorted(captcha_engines)} for '{original_keyword}' (tried {engines_tried}) - counting as not found/FAILED", extra={'action': 'CAPTCHA_ALL_ENGINES', 'status': 'FAILED', 'engine': engine_name})
                except Exception:
                    pass
            elif captcha_engines:
                try:
                    session_logger.warning(f"Website not found for '{current_search_keyword}' on {engine_name} after trying {engines_tried} (captcha on {sorted(captcha_engines)})", extra={'action': 'WEBSITE_NOT_FOUND', 'status': 'FAILED', 'engine': engine_name})
                except Exception:
                    pass
            else:
                try:
                    session_logger.warning(f"Website not found for '{current_search_keyword}' after trying {engines_tried} on all engines", extra={'action': 'WEBSITE_NOT_FOUND', 'status': 'FAILED', 'engine': engine_name})
                except Exception:
                    pass
            failure_count = 1
            status = "FAILED"
            with _STATS_LOCK:
                if stop_event.is_set():
                    status = "INTERRUPTED"
                    return
                if not any(d.get('keyword') == original_keyword for d in stats["failed"]):
                    if not any(d.get('keyword') == original_keyword for d in stats.get("interrupted", [])):
                        stats["failed"].append({"keyword": original_keyword, "engine": engine_name})

    except (BrowserError, SearchEngineError, CaptchaDetectedError, TargetNotFoundError, ConfigError) as error:
        # Expected business failures — graceful, counted as FAILED, not a bug
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
                # Expected: log as warning with context, keep traceback at info
                session_logger.warning(f"Session business failure ({original_keyword} | {engine_name}): {error} [{type(error).__name__}]", extra={'action': 'SESSION_BUSINESS_FAILURE', 'status': 'FAILED', 'error_message': str(error)})
            except Exception:
                logger.warning(f"Session business failure ({original_keyword} | {engine_name}): {error} [{type(error).__name__}]")
        else:
            status = "INTERRUPTED"
    except UnhandledAutomationError as error:
        # Wrapped unexpected — log as error with cause
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
                session_logger.error(f"Session unhandled error ({original_keyword} | {engine_name}): {error} cause={error.cause}", exc_info=True, extra={'action': 'SESSION_UNHANDLED', 'status': 'FAILED', 'error_message': str(error)})
            except Exception:
                logger.error(f"Session unhandled error ({original_keyword} | {engine_name}): {error} cause={error.cause}", exc_info=True)
        else:
            status = "INTERRUPTED"
    except Exception as error:
        # Truly unexpected bug — wrap and log as error, still graceful
        wrapped = wrap_unexpected(error, f"run_session {original_keyword}|{engine_name}")
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
                session_logger.error(f"Session unexpected bug ({original_keyword} | {engine_name}): {wrapped}", exc_info=True, extra={'action': 'SESSION_BUG', 'status': 'FAILED', 'error_message': str(wrapped)})
            except Exception:
                logger.error(f"Session unexpected bug ({original_keyword} | {engine_name}): {wrapped}", exc_info=True)
        else:
            status = "INTERRUPTED"
    finally:
        # Always cleanup driver — close first then unregister (so global close_active_drivers can retry if needed)
        if driver:
            closed = False
            try:
                closed = close_browser(driver, timeout=4.0)
            except Exception as e:
                closed = False
                try:
                    session_logger.warning(f"Browser close failed: {e}", extra={'action': 'BROWSER_CLOSE', 'status': 'FAILED', 'error_message': str(e)})
                except Exception:
                    logger.warning(f"Browser close failed: {e}")
            # Ensure driver is removed from active set; mark closed correctly for global dedup
            try:
                with _ACTIVE_DRIVERS_LOCK:
                    _ACTIVE_DRIVERS.discard(driver)
                with _CLOSED_DRIVER_IDS_LOCK:
                    if closed:
                        _CLOSED_DRIVER_IDS.add(id(driver))
                    else:
                        # Ensure failed stays retryable
                        _CLOSED_DRIVER_IDS.discard(id(driver))
            except Exception:
                pass
            # Extra profile-based kill if quit didn't fully close (edge leaves msedge.exe)
            if not closed:
                try:
                    from browser.browser import _kill_browsers_by_profile
                    profile = getattr(driver, "_seo_profile_dir", None)
                    if profile:
                        _kill_browsers_by_profile(str(profile))
                except Exception:
                    pass
                try:
                    _kill_orphaned_browser_profiles()
                except Exception:
                    pass

        session_end_time = datetime.now()
        if status is None:
            status = "FAILED" if failure_count > 0 else "COMPLETED"
        if stop_event.is_set():
            status = "INTERRUPTED"
            with _STATS_LOCK:
                if not any(d.get('keyword') == original_keyword for d in stats["success"]):
                    if not any(d.get('keyword') == original_keyword for d in stats["failed"]):
                        if not any(d.get('keyword') == original_keyword for d in stats["interrupted"]):
                            stats["interrupted"].append({"keyword": original_keyword, "engine": engine_name})

        _safe_update_run(run_id, session_end_time, status, success_count, failure_count, retry_count, fallback_used=fallback_used, search_keyword=current_search_keyword)


def _session_worker(job_queue, config, stop_event, stats, search_engines=None, all_engine_names=None):
    while not stop_event.is_set():
        job = None
        try:
            try:
                job = job_queue.get_nowait()
            except queue.Empty:
                return
            keyword, engine_name, engine = job
            try:
                run_session(keyword, config, engine_name, engine, stop_event, stats, search_engines=search_engines, all_engine_names=all_engine_names)
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
        "interrupted": [],
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
            w = threading.Thread(target=_session_worker, args=(job_queue, config, stop_event, stats, search_engines, engine_names), daemon=True, name=f"Worker-{i+1}")
            workers.append(w)
        except Exception as e:
            logger.error(f"Failed to create worker {i}: {e}")

    for w in workers:
        try:
            w.start()
        except Exception as e:
            logger.error(f"Failed to start worker {w.name}: {e}", exc_info=True)

    interrupted = False
    try:
        # Block until all jobs are processed, checking browser health periodically
        while job_queue.unfinished_tasks > 0:
            if stop_event.is_set():
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        interrupted = True
        # Silence noisy retry logs BEFORE anything else to prevent flood
        try:
            from utils.logger import silence_noisy_loggers
            silence_noisy_loggers()
        except Exception:
            pass
        try:
            import logging as _logging
            for _n in ("urllib3", "urllib3.connectionpool", "selenium", "selenium.webdriver.remote.remote_connection"):
                _logging.getLogger(_n).setLevel(_logging.ERROR)
        except Exception:
            pass
        logger.info("\nCtrl+C detected. Stopping all browser sessions...", extra={'action': 'SESSION_INTERRUPT', 'status': 'RUNNING'})
        stop_event.set()
        # Immediately close browsers to unblock workers stuck in driver.get / WebDriverWait
        try:
            close_active_drivers(stop_event)
        except Exception:
            pass
        # Do not re-raise — return partial stats so main.py can still print summary (even on Ctrl+C)
    except Exception as e:
        logger.error(f"Unexpected error in parallel runner: {e}", exc_info=True)
        stop_event.set()
    finally:
        # Ensure cleanup happens whether jobs complete or are interrupted
        stop_event.set()
        # Silence again before closing — guarantees no NewConnectionError spam
        try:
            from utils.logger import silence_noisy_loggers
            silence_noisy_loggers()
        except Exception:
            pass
        # Immediately force close browsers to unblock workers stuck in blocking Selenium calls
        try:
            close_active_drivers(stop_event)
        except Exception:
            pass
        # Then wait for workers to notice closure and exit gracefully
        for w in workers:
            try:
                w.join(timeout=4)
                if w.is_alive():
                    if not interrupted:
                        logger.warning(f"Worker {w.name} did not exit cleanly")
                    else:
                        logger.info(f"Worker {w.name} still alive after interrupt — forcing browser close")
            except Exception as e:
                msg = str(e).lower()
                if "newconnectionerror" not in msg and "connection refused" not in msg:
                    try:
                        logger.warning(f"Worker join failed for {w.name}: {e}")
                    except Exception:
                        pass
        # Second force close for any drivers that were registered after first close or still alive
        try:
            close_active_drivers(stop_event)
        except Exception as e:
            msg = str(e).lower()
            if "newconnectionerror" not in msg and "connection refused" not in msg:
                try:
                    logger.warning(f"close_active_drivers failed: {e}")
                except Exception:
                    pass
        # Small pause then final check — looped to ensure edge/msedge is killed
        try:
            import time as _t
            for _ in range(3):
                _t.sleep(0.5)
                try:
                    close_active_drivers(stop_event)
                except Exception:
                    pass
                # Also try direct profile sweep via browser helper (covers drivers removed from set)
                try:
                    from browser.browser import _kill_browsers_by_profile
                    # Already done via _kill_orphaned_browser_profiles inside close_active_drivers,
                    # but do an extra sweep after workers may have removed entries
                    _kill_orphaned_browser_profiles()
                except Exception:
                    pass
        except Exception:
            pass
        for w in workers:
            try:
                if w.is_alive():
                    w.join(timeout=2)
                    if w.is_alive():
                        # Force kill any remaining browsers then give workers one more chance
                        try:
                            close_active_drivers(stop_event)
                            _kill_orphaned_browser_profiles()
                        except Exception:
                            pass
                        w.join(timeout=1)
                        if w.is_alive() and not interrupted:
                            logger.warning(f"Worker {w.name} did not exit cleanly after forced close")
                        elif w.is_alive():
                            logger.info(f"Worker {w.name} still alive after interrupt — done (browsers killed)")
            except Exception as e:
                msg = str(e).lower()
                if "newconnectionerror" not in msg and "connection refused" not in msg:
                    try:
                        logger.warning(f"Worker join failed for {w.name}: {e}")
                    except Exception:
                        pass
        # Final OS-level orphan sweep — ensures no msedge/chrome ghost windows remain
        try:
            _kill_orphaned_browser_profiles()
            # Last resort Windows taskkill by profile path via browser helper
            from browser.browser import _kill_browsers_by_profile
            import pathlib as _pl
            bp_root = _pl.Path.cwd() / "browser_profiles"
            if bp_root.exists():
                # Kill any chrome/msedge still referencing browser_profiles
                try:
                    import psutil as _ps4
                    root_norm = str(bp_root).replace("\\", "/").lower()
                    for proc in _ps4.process_iter(["pid", "name", "cmdline"]):
                        try:
                            cmd = proc.info.get("cmdline")
                            if cmd and root_norm in " ".join(cmd).replace("\\", "/").lower():
                                try:
                                    proc.kill()
                                except Exception:
                                    pass
                        except Exception:
                            continue
                except Exception:
                    pass
        except Exception:
            pass
        # If interrupted, drain remaining queued jobs and mark as interrupted
        # so Session Summary Total (=success+failed+interrupted) matches Automation total
        # Also handle jobs that were taken by workers but not yet recorded (in-progress)
        if interrupted:
            try:
                remaining = []
                while True:
                    try:
                        kw, eng_name, _ = job_queue.get_nowait()
                        remaining.append((kw, eng_name))
                        try:
                            job_queue.task_done()
                        except Exception:
                            pass
                    except queue.Empty:
                        break
                for kw, eng_name in remaining:
                    with _STATS_LOCK:
                        if not any(d.get('keyword') == kw for d in stats.get("success", [])):
                            if not any(d.get('keyword') == kw for d in stats.get("failed", [])):
                                if not any(d.get('keyword') == kw for d in stats.get("interrupted", [])):
                                    stats["interrupted"].append({"keyword": kw, "engine": eng_name})
                # Also add any job that was taken but worker didn't record before being forced closed
                # Compare all jobs vs accounted keywords
                try:
                    all_jobs_keywords = [(kw, eng) for kw, eng, _ in jobs]
                    accounted = {d.get('keyword') for d in stats.get("success", []) + stats.get("failed", []) + stats.get("interrupted", [])}
                    for kw, eng in all_jobs_keywords:
                        if kw not in accounted:
                            with _STATS_LOCK:
                                # Double-check still not accounted (race)
                                if kw not in {d.get('keyword') for d in stats.get("success", []) + stats.get("failed", []) + stats.get("interrupted", [])}:
                                    stats["interrupted"].append({"keyword": kw, "engine": eng})
                                    accounted.add(kw)
                except Exception:
                    pass
            except Exception:
                pass
        # Final summary log — always, even on Ctrl+C
        try:
            total_now = len(stats.get("success", [])) + len(stats.get("failed", [])) + len(stats.get("interrupted", []))
            logger.info(f"Parallel run finished: total={stats.get('total',0)} success={len(stats.get('success',[]))} failed={len(stats.get('failed',[]))} interrupted={len(stats.get('interrupted',[]))} (session_total={total_now})", extra={'action': 'SESSION_FINISHED', 'status': 'SUCCESS' if not stats.get('failed') else 'COMPLETED'})
        except Exception:
            pass
        if interrupted:
            logger.info("Parallel run interrupted by user — partial stats will be returned.", extra={'action': 'SESSION_INTERRUPT', 'status': 'INTERRUPTED'})

    return stats