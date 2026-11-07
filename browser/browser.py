"""
browser.py
 
Browser setup and lifecycle helpers.
"""
 
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
 
from selenium.common.exceptions import WebDriverException
from seleniumbase import Driver
 
from utils.exceptions import (
    BrowserBinaryNotFoundError,
    BrowserStartupError,
    UnsupportedBrowserError,
)
 
 
_BROWSER_START_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Browser profile disk-space management
#
# Every session gets its own throw-away profile folder
# (<profile_root>/<browser>_<thread>_<uuid8>). Nothing is ever re-used, so the
# folder is deleted as soon as the session's browser is closed, and anything a
# crash left behind is swept once at start-up.
# ---------------------------------------------------------------------------
_PROFILE_NAME_RE = re.compile(r"^(chrome|edge|firefox|opera|brave)_\d+_[0-9a-f]{8}$")
DEFAULT_STALE_PROFILE_MINUTES = 10

_ACTIVE_PROFILES: set = set()          # profiles created by THIS process and still open
_ACTIVE_PROFILES_LOCK = threading.Lock()
_STALE_SWEEP_DONE = False
_STALE_SWEEP_LOCK = threading.Lock()


def _norm_path(p) -> str:
    return os.path.normcase(os.path.abspath(str(p)))


def _is_inside(path, root) -> bool:
    """True if path is strictly inside root (never root itself)."""
    try:
        p, r = _norm_path(path), _norm_path(root)
        return p != r and os.path.commonpath([p, r]) == r
    except ValueError:
        return False


def _register_profile(path) -> None:
    with _ACTIVE_PROFILES_LOCK:
        _ACTIVE_PROFILES.add(_norm_path(path))


def _unregister_profile(path) -> None:
    with _ACTIVE_PROFILES_LOCK:
        _ACTIVE_PROFILES.discard(_norm_path(path))


def _rmtree_onerror(func, path, _exc):
    """Clear a read-only flag and retry once; give up silently otherwise."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def _dir_size_mb(path) -> float:
    total = 0
    try:
        for dirpath, _dirs, files in os.walk(path):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(dirpath, name))
                except OSError:
                    pass
    except Exception:
        pass
    return total / (1024 * 1024)


def remove_profile_dir(profile_dir, profile_root, retries: int = 6, delay: float = 0.5) -> bool:
    """Delete one session profile folder. Returns True once it is gone.

    Safety: refuses to delete anything that is not strictly inside
    profile_root, so a wrong path can never wipe the user's real browser
    profile or the root itself. Windows releases file handles a moment after
    the browser dies, so the delete is retried a few times.
    """
    if not profile_dir or not profile_root or not _is_inside(profile_dir, profile_root):
        return False
    kw = {"onexc": _rmtree_onerror} if sys.version_info >= (3, 12) else {"onerror": _rmtree_onerror}
    try:
        for attempt in range(retries):
            if not os.path.exists(profile_dir):
                return True
            try:
                shutil.rmtree(profile_dir, **kw)
            except Exception:
                pass
            if not os.path.exists(profile_dir):
                return True
            time.sleep(delay)
        return not os.path.exists(profile_dir)
    finally:
        _unregister_profile(profile_dir)


def _profile_in_use(profile_dir) -> bool:
    """True if any running process was launched with this profile path."""
    import psutil
    target = os.path.normpath(str(profile_dir)).replace("\\", "/").lower()
    for proc in psutil.process_iter(["cmdline"]):
        try:
            cmdline = proc.info.get("cmdline")
            if cmdline and target in " ".join(cmdline).replace("\\", "/").lower():
                return True
        except Exception:
            continue
    return False


def cleanup_stale_profiles(profile_root, stale_after_minutes=DEFAULT_STALE_PROFILE_MINUTES) -> dict:
    """Remove profile folders left behind by crashed / killed earlier runs.

    A folder is only removed when ALL of these hold, so sessions running in
    parallel (same process or another bot process) are never touched:
      * its name matches our own <browser>_<thread>_<uuid8> pattern
      * it is not registered as active by this process
      * it is older than stale_after_minutes (covers the short window between
        folder creation and browser launch)
      * no running process has it on its command line
    """
    stats = {"removed": 0, "skipped": 0, "failed": 0, "freed_mb": 0.0}
    log = logging.getLogger(__name__)
    if not profile_root or not os.path.isdir(profile_root):
        return stats
    try:
        import psutil  # noqa: F401
    except ImportError:
        log.warning("Stale profile cleanup skipped: psutil is not installed.")
        return stats

    try:
        min_age = max(0.0, float(stale_after_minutes)) * 60
    except (TypeError, ValueError):
        min_age = DEFAULT_STALE_PROFILE_MINUTES * 60
    now = time.time()

    try:
        names = os.listdir(profile_root)
    except OSError:
        return stats

    for name in names:
        path = os.path.join(profile_root, name)
        if not _PROFILE_NAME_RE.match(name) or os.path.islink(path) or not os.path.isdir(path):
            continue
        with _ACTIVE_PROFILES_LOCK:
            if _norm_path(path) in _ACTIVE_PROFILES:
                stats["skipped"] += 1
                continue
        try:
            if now - os.path.getmtime(path) < min_age or _profile_in_use(path):
                stats["skipped"] += 1
                continue
        except Exception:
            stats["skipped"] += 1
            continue
        size_mb = _dir_size_mb(path)
        if remove_profile_dir(path, profile_root):
            stats["removed"] += 1
            stats["freed_mb"] += size_mb
        else:
            stats["failed"] += 1

    if stats["removed"] or stats["failed"]:
        log.info(
            "Stale browser profile cleanup: removed %d folder(s), freed %.1f MB, %d could not be removed.",
            stats["removed"], stats["freed_mb"], stats["failed"],
        )
    return stats


def _sweep_stale_profiles_once(profile_root, stale_after_minutes) -> None:
    """Run the stale-profile sweep a single time per process (first browser start)."""
    global _STALE_SWEEP_DONE
    with _STALE_SWEEP_LOCK:
        if _STALE_SWEEP_DONE:
            return
        _STALE_SWEEP_DONE = True
    try:
        cleanup_stale_profiles(profile_root, stale_after_minutes)
    except Exception as e:
        logging.getLogger(__name__).debug(f"Stale profile cleanup failed: {e}")


def sweep_stale_profiles_at_startup(config) -> None:
    """Run the stale-profile sweep at application start (before any browser opens).

    Uses the same profile root / stale threshold as setup_browser, and the same
    once-per-process guard, so the later call inside setup_browser is a no-op.
    """
    try:
        browser_config = (config or {}).get("browser", {}) or {}
        profile_root = browser_config.get(
            "profile_dir",
            os.path.join(os.getcwd(), "browser_profiles"),
        )
        _sweep_stale_profiles_once(
            profile_root,
            browser_config.get("stale_profile_minutes", DEFAULT_STALE_PROFILE_MINUTES),
        )
    except Exception as e:
        logging.getLogger(__name__).debug(f"Startup profile cleanup failed: {e}")
 
 
def get_brave_binary():
    """
    Locate Brave browser binary.
    """
 
    candidates = []
 
    if sys.platform.startswith("linux"):
        candidates.extend(
            [
                shutil.which("brave-browser"),
                shutil.which("brave"),
            ]
        )
 
    env_path = os.getenv("BRAVE_BINARY")
    if env_path:
        candidates.append(env_path)
 
    if sys.platform.startswith("win"):
        candidates.extend(
            [
                r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
                r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
            ]
        )
 
    for path in candidates:
        if path and os.path.exists(path):
            return path
 
    return None
 
 
def prepare_browser_drivers(config):
    """
    Prepare browser drivers required by the configuration.
    """

    browser_cfg = config.get("browser", {}) if isinstance(config, dict) else {}
    dist = browser_cfg.get("distribution")
    if isinstance(dist, dict):
        browsers = [k for k, v in dist.items() if float(v or 0) > 0]
    elif isinstance(dist, (list, tuple)):
        browsers = list(dist)
    else:
        browsers = browser_cfg.get("browsers") or [browser_cfg.get("name", "chrome")]

    if not browsers:
        browsers = ["chrome"]

    if isinstance(browsers, str):
        browsers = [browsers]

    python_exe = sys.executable or "python"

    for browser in browsers:
        browser = str(browser).lower().strip()

        try:
            if browser == "chrome":
                result = subprocess.run(
                    [python_exe, "-m", "seleniumbase", "install", "uc_driver"],
                    capture_output=True, text=True, check=False,
                )
                if result.returncode != 0:
                    raise BrowserStartupError(f"uc_driver install failed: {result.stderr[:300]}", browser=browser)
            elif browser == "edge":
                result = subprocess.run(
                    [python_exe, "-m", "seleniumbase", "install", "edgedriver"],
                    capture_output=True, text=True, check=False,
                )
                if result.returncode != 0:
                    raise BrowserStartupError(f"edgedriver install failed: {result.stderr[:300]}", browser=browser)
            elif browser == "firefox":
                result = subprocess.run(
                    [python_exe, "-m", "seleniumbase", "install", "geckodriver"],
                    capture_output=True, text=True, check=False,
                )
                if result.returncode != 0:
                    raise BrowserStartupError(f"geckodriver install failed: {result.stderr[:300]}", browser=browser)
            elif browser in ("opera", "brave"):
                result = subprocess.run(
                    [python_exe, "-m", "seleniumbase", "install", "chromedriver"],
                    capture_output=True, text=True, check=False,
                )
                if result.returncode != 0:
                    raise BrowserStartupError(f"chromedriver install failed: {result.stderr[:300]}", browser=browser)
            else:
                raise UnsupportedBrowserError(f"Unsupported browser: {browser}", browser=browser)
        except (BrowserStartupError, UnsupportedBrowserError):
            raise
        except OSError as e:
            raise BrowserStartupError(f"Driver install OSError for {browser}: {e}", browser=browser, cause=e) from e
        except Exception as e:
            raise BrowserStartupError(f"Driver install failed for {browser}: {e}", browser=browser, cause=e) from e


def get_chromium_args():
    """
    Common Chromium arguments.
    """

    return [
        "--mute-audio",
        "--disable-notifications",
    ]


def setup_browser(config, browser_name="chrome", proxy_url=None):
    """
    Start and configure a browser instance.
    Caller (run_session) handles fallback to 'chrome' if this fails.

    Args:
        config: project configuration dict.
        browser_name: chrome / edge / firefox / opera / brave (defaults to chrome).
        proxy_url: optional proxy for IP bouncing. Format accepted by
            SeleniumBase Driver: "SERVER:PORT", "USER:PASS@SERVER:PORT",
            or full URL "http(s)://USER:PASS@HOST:PORT" / "socks5://...".
            None/empty = direct connection.
    """

    browser_name = str(browser_name).lower().strip() if browser_name else "chrome"

    browser_config = config.get("browser", {})

    headless = browser_config.get("headless", False) or (str(browser_config.get("mode", "")).lower() == "headless")
    maximize = browser_config.get("maximize", True)
    # In headless, maximizing is no-op and can cause errors on some drivers
    if headless:
        maximize = False

    import uuid as _uuid

    thread_id = threading.get_ident()

    profile_root = browser_config.get(
        "profile_dir",
        os.path.join(os.getcwd(), "browser_profiles"),
    )

    # Pre-run cleanup: once per process, delete leftovers of crashed/stale sessions.
    _sweep_stale_profiles_once(
        profile_root,
        browser_config.get("stale_profile_minutes", DEFAULT_STALE_PROFILE_MINUTES),
    )

    # uuid avoids collisions from recycled OS thread IDs + stale lock files.
    # Startup is retried with a FRESH profile per attempt: transient failures
    # like "cannot connect to chrome at 127.0.0.1:9222 / chrome not reachable"
    # almost always succeed on a clean second attempt.
    _start_logger = logging.getLogger(__name__)
    _startup_attempts = 3
    last_error = None
    driver = None
    profile_path = ""
    for attempt in range(1, _startup_attempts + 1):
        profile_path = os.path.join(
            profile_root,
            f"{browser_name}_{thread_id}_{_uuid.uuid4().hex[:8]}",
        )

        _register_profile(profile_path)
        try:
            os.makedirs(profile_path, exist_ok=True)
        except OSError as e:
            _unregister_profile(profile_path)
            last_error = BrowserStartupError(f"Failed to create profile dir {profile_path}: {e}", browser=browser_name, cause=e)
            continue

        # --- IP bouncing: per-session proxy (None = direct connection) ---
        proxy_kwargs: dict = {}
        try:
            _proxy = (proxy_url or "").strip() if isinstance(proxy_url, str) else proxy_url
            if _proxy:
                proxy_kwargs["proxy"] = _proxy
                # Authenticated proxies in parallel threads need isolated
                # auth extensions, otherwise threads share one proxy.zip.
                if "@" in str(_proxy):
                    proxy_kwargs["multi_proxy"] = True
        except Exception:
            proxy_kwargs = {}

        with _BROWSER_START_LOCK:

            try:
                if browser_name == "chrome":

                    driver = Driver(
                        browser="chrome",
                        uc=True,
                        user_data_dir=profile_path,
                        headless=headless,
                        chromium_arg=get_chromium_args(),
                        **proxy_kwargs,
                    )

                elif browser_name == "edge":

                    driver = Driver(
                        browser="edge",
                        uc=False,
                        user_data_dir=profile_path,
                        headless=headless,
                        chromium_arg=get_chromium_args(),
                        **proxy_kwargs,
                    )

                elif browser_name == "firefox":

                    driver = Driver(
                        browser="firefox",
                        uc=False,
                        headless=headless,
                        user_data_dir=profile_path,
                        firefox_pref="media.volume_scale=0.0",
                        **proxy_kwargs,
                    )

                elif browser_name == "opera":

                    driver = Driver(
                        browser="opera",
                        uc=False,
                        user_data_dir=profile_path,
                        headless=headless,
                        chromium_arg=get_chromium_args(),
                        **proxy_kwargs,
                    )

                    try:
                        driver.execute_cdp_cmd(
                            "Browser.setPermission",
                            {
                                "permission": {
                                    "name": "geolocation",
                                },
                                "setting": "denied",
                                "origin": "https://www.google.com",
                            },
                        )
                    except WebDriverException as e:
                        # Non-fatal: geolocation deny is best-effort
                        import logging as _logging
                        _logging.getLogger(__name__).warning(f"Opera geolocation deny failed: {e}", exc_info=False)
                    except Exception as e:
                        import logging as _logging
                        _logging.getLogger(__name__).warning(f"Opera geolocation deny unexpected error: {e}", exc_info=False)

                elif browser_name == "brave":

                    brave_binary = get_brave_binary()

                    if not brave_binary:
                        raise BrowserBinaryNotFoundError(
                            "Brave browser binary was not found.", browser=browser_name
                        )

                    driver = Driver(
                        browser="chrome",
                        binary_location=brave_binary,
                        uc=True,
                        user_data_dir=profile_path,
                        headless=headless,
                        chromium_arg=get_chromium_args(),
                        **proxy_kwargs,
                    )

                else:
                    raise UnsupportedBrowserError(
                        f"Unsupported browser: {browser_name}", browser=browser_name
                    )
            except (BrowserBinaryNotFoundError, UnsupportedBrowserError):
                remove_profile_dir(profile_path, profile_root)
                raise
            except Exception as e:
                last_error = e
                driver = None
                # Bury the zombie from THIS attempt only: the profile path is
                # unique per attempt, so sibling sessions and the user's own
                # Chrome are never touched.
                try:
                    _kill_browsers_by_profile(profile_path)
                except Exception:
                    pass
                try:
                    remove_profile_dir(profile_path, profile_root)
                except Exception:
                    pass

        if driver is not None:
            if attempt > 1:
                _start_logger.info(f"Browser started for {browser_name} on attempt {attempt}/{_startup_attempts}")
            break
        if attempt < _startup_attempts:
            _start_logger.warning(f"Browser startup attempt {attempt}/{_startup_attempts} failed for {browser_name}: {last_error}. Retrying with a fresh profile...")
            time.sleep(4 * attempt)

    if driver is None:
        raise BrowserStartupError(f"Browser startup failed for {browser_name} after {_startup_attempts} attempts: {last_error}", browser=browser_name, cause=last_error)

    if maximize:
        try:
            driver.maximize_window()
        except WebDriverException as e:
            import logging as _logging
            _logging.getLogger(__name__).warning(f"Maximize failed for {browser_name}: {e}", exc_info=False)
        except Exception as e:
            import logging as _logging
            _logging.getLogger(__name__).warning(f"Maximize unexpected error for {browser_name}: {e}", exc_info=False)

    # Fail fast on dead network instead of hanging 120s (Oct-08 logs:
    # HTTPConnectionPool Read timed out). Session code fails over to the
    # next engine/job quickly; page content still loads normally otherwise.
    try:
        driver.set_page_load_timeout(45)
    except Exception:
        pass
    try:
        driver.set_script_timeout(30)
    except Exception:
        pass

    # Stash metadata for forced kill by profile path (used by close_browser to find orphaned browser processes)
    try:
        driver._seo_profile_dir = profile_path  # type: ignore[attr-defined]
        driver._seo_profile_root = profile_root  # type: ignore[attr-defined]
        driver._seo_browser_name = browser_name  # type: ignore[attr-defined]
        driver._seo_proxy = (proxy_kwargs.get("proxy") if proxy_kwargs else None)  # type: ignore[attr-defined]
    except Exception:
        pass

    return driver
 
 
def _kill_process_tree_psutil(pid: int, timeout: float = 2.0) -> bool:
    """Kill pid and all children via psutil. Returns True if pid no longer exists."""
    try:
        import psutil
        try:
            parent = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return True
        # Collect children recursively
        try:
            children = parent.children(recursive=True)
        except Exception:
            children = []
        for child in children:
            try:
                child.terminate()
            except Exception:
                pass
        try:
            parent.terminate()
        except Exception:
            pass
        # Wait briefly
        try:
            _, alive = psutil.wait_procs(children + [parent], timeout=timeout)
        except Exception:
            _, alive = [], children + [parent]
        for p in alive:
            try:
                p.kill()
            except Exception:
                pass
        try:
            psutil.wait_procs(alive, timeout=1)
        except Exception:
            pass
        # Verify
        try:
            psutil.Process(pid)
            return False
        except psutil.NoSuchProcess:
            return True
        except Exception:
            return False
    except ImportError:
        return False
    except Exception:
        return False


def _kill_browsers_by_profile(profile_dir: str) -> None:
    """Kill chrome.exe / msedge.exe (and related) that were launched with --user-data-dir containing profile_dir.
    Safe: matches by full profile path fragment, so it won't kill user's normal profile.
    """
    if not profile_dir:
        return
    # Normalize for comparison: use forward slashes and lower for windows
    try:
        import psutil
        norm_target = os.path.normpath(profile_dir).replace("\\", "/").lower()
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                info = proc.info
                cmdline = info.get("cmdline")
                if not cmdline:
                    continue
                # cmdline is list
                try:
                    cmd_joined = " ".join(cmdline).replace("\\", "/").lower()
                except Exception:
                    continue
                if norm_target in cmd_joined:
                    # Matched our isolated profile — kill tree
                    try:
                        # First try graceful terminate of whole tree
                        _kill_process_tree_psutil(info["pid"])
                    except Exception:
                        pass
                    # Fallback taskkill for this pid
                    try:
                        if sys.platform.startswith("win"):
                            _kw = {"capture_output": True, "timeout": 3}
                            if sys.platform.startswith("win"):
                                _kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
                            subprocess.run(["taskkill", "/F", "/T", "/PID", str(info["pid"])], **_kw)
                    except Exception:
                        pass
                    try:
                        # Direct kill if still alive
                        proc.kill()
                    except Exception:
                        pass
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except Exception:
                continue
    except ImportError:
        pass
    except Exception:
        pass
    # Fallback via wmic/cmdline search if psutil failed or partial (Windows)
    if sys.platform.startswith("win"):
        try:
            import subprocess as _sp
            try:
                ps_cmd = (
                    f"Get-CimInstance Win32_Process | Where-Object {{ $_.CommandLine -like '*{profile_dir.replace(chr(39), chr(39)+chr(39))}*' }} "
                    f"| ForEach-Object {{ try {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }} catch {{}} }}"
                )
                _kw2 = {"capture_output": True, "timeout": 5}
                if sys.platform.startswith("win"):
                    _kw2["creationflags"] = 0x08000000
                _sp.run(["powershell", "-NoProfile", "-Command", ps_cmd], **_kw2)
            except Exception:
                pass
        except Exception:
            pass


def _force_kill_service(driver) -> bool:
    """Force-kill driver.service process and its browser children. Returns True if service pid gone."""
    killed = False
    # 1) Try psutil tree kill on service pid
    try:
        svc = getattr(driver, "service", None)
        if svc is not None:
            # Prefer svc.process.pid, but also check alternative attrs
            proc = getattr(svc, "process", None)
            pid = None
            if proc is not None:
                pid = getattr(proc, "pid", None)
                # Some selenium versions store _process or process
                if pid is None:
                    # Try alternative nested
                    try:
                        pid = proc.pid
                    except Exception:
                        pid = None
            # Also check svc._process or svc.process_handle
            if pid is None:
                for attr in ("_process", "process_handle", "_proc"):
                    try:
                        alt = getattr(svc, attr, None)
                        if alt is not None:
                            pid = getattr(alt, "pid", None)
                            if pid:
                                proc = alt
                                break
                    except Exception:
                        pass
            if pid:
                # Kill tree via psutil
                try:
                    if _kill_process_tree_psutil(int(pid)):
                        killed = True
                except Exception:
                    pass
                # Also taskkill /T as extra guarantee (Windows kills whole tree)
                try:
                    if sys.platform.startswith("win"):
                        _kw3 = {"capture_output": True, "timeout": 3}
                        if sys.platform.startswith("win"):
                            _kw3["creationflags"] = 0x08000000
                        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], **_kw3)
                        killed = True
                except Exception:
                    pass
                # Direct Popen terminate/kill if still alive
                try:
                    if proc is not None and hasattr(proc, "poll"):
                        try:
                            if proc.poll() is None:
                                try:
                                    proc.terminate()
                                    try:
                                        proc.wait(timeout=2)
                                    except Exception:
                                        try:
                                            proc.kill()
                                        except Exception:
                                            pass
                                except Exception:
                                    pass
                        except Exception:
                            pass
                except Exception:
                    pass
            # Try svc.stop() even after kills (may be no-op if already dead)
            try:
                svc.stop()
                killed = True
            except Exception:
                pass
    except Exception:
        pass
    # 2) Kill browser processes by profile dir (most reliable for orphaned msedge/chrome)
    try:
        profile_dir = getattr(driver, "_seo_profile_dir", None) or getattr(driver, "_sb_profile_dir", None)
        if profile_dir:
            _kill_browsers_by_profile(str(profile_dir))
            killed = True
    except Exception:
        pass
    # 3) Fallback: try driver.close() if service gone but window still open (non-service mode)
    return killed


def close_browser(driver, timeout: float = 4.0):
    """
    Safely close browser instance — suppresses NewConnectionError spam on shutdown.
    Uses timeout + service kill + profile-based kill fallback to avoid hanging on Ctrl+C and ensure
    no browser remains open after summary. Handles chrome and edge (msedge.exe) одинаково.
    Returns True if closed (or force-killed), False if kill appears to have failed.
    """

    if driver is None:
        return True

    # Temporarily silence urllib3/selenium retries during quit (prevents flood on Ctrl+C)
    import logging as _logging
    _silenced = []
    try:
        for _name in ("urllib3", "urllib3.connectionpool", "selenium", "selenium.webdriver.remote.remote_connection"):
            _lg = _logging.getLogger(_name)
            _silenced.append((_lg, _lg.level))
            _lg.setLevel(_logging.ERROR)
    except Exception:
        pass

    closed = False
    quit_error = None
    try:
        # Run quit with timeout — driver.quit() can hang if browser is busy (Ctrl+C mid-navigation)
        import threading as _th
        result = {"err": None, "done": False}

        def _do_quit():
            try:
                driver.quit()
                result["done"] = True
            except Exception as e:
                result["err"] = e
        t = _th.Thread(target=_do_quit, daemon=True)
        t.start()
        t.join(timeout=timeout)
        if t.is_alive():
            quit_error = TimeoutError(f"driver.quit() hung >{timeout}s")
        elif result["err"] is not None:
            quit_error = result["err"]
        elif result["done"]:
            closed = True
    except Exception as e:
        quit_error = e

    # Force fallback if quit hung or raised — always do aggressive kill (crucial for edge)
    if not closed:
        force_killed = False
        try:
            force_killed = _force_kill_service(driver)
        except Exception:
            pass
        # If service kill didn't report success, still try legacy steps
        if not force_killed:
            try:
                # Legacy: try service stop / process kill (seleniumbase / selenium)
                svc = getattr(driver, "service", None)
                if svc is not None:
                    try:
                        svc.stop()
                        closed = True
                    except Exception:
                        pass
                    try:
                        proc = getattr(svc, "process", None)
                        if proc is not None:
                            try:
                                if hasattr(proc, "poll") and proc.poll() is None:
                                    try:
                                        proc.terminate()
                                        try:
                                            proc.wait(timeout=2)
                                        except Exception:
                                            try:
                                                proc.kill()
                                            except Exception:
                                                pass
                                    except Exception:
                                        pass
                                closed = True
                            except Exception:
                                pass
                            try:
                                import subprocess as _sp2
                                pid = getattr(proc, "pid", None)
                                if pid and sys.platform.startswith("win"):
                                    try:
                                        _kw4 = {"capture_output": True, "timeout": 3}
                                        if sys.platform.startswith("win"):
                                            _kw4["creationflags"] = 0x08000000
                                        _sp2.run(["taskkill", "/F", "/T", "/PID", str(pid)], **_kw4)
                                        closed = True
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                    except Exception:
                        pass
                if not closed:
                    try:
                        driver.close()
                        closed = True
                    except Exception:
                        pass
            except Exception:
                pass
        else:
            closed = True
        # Final fallback: kill by profile path even if service kill succeeded but browser still orphaned
        try:
            profile_dir = getattr(driver, "_seo_profile_dir", None)
            if profile_dir:
                _kill_browsers_by_profile(str(profile_dir))
                closed = True
        except Exception:
            pass
        # Also attempt OS-wide check for orphaned driver browsers with same profile
        # Log only genuine errors (not shutdown noise)
        if quit_error is not None:
            msg = str(quit_error).lower()
            if "newconnectionerror" not in msg and "connection refused" not in msg and "connectionreseterror" not in msg and "max retries" not in msg and "timed out" not in msg and "hung" not in msg:
                _logging.getLogger(__name__).warning(f"Browser quit forced after {quit_error}", exc_info=False)

    # After successful quit, also ensure no orphaned browser process remains for this profile (edge often leaves msedge.exe)
    if closed:
        try:
            profile_dir = getattr(driver, "_seo_profile_dir", None)
            if profile_dir:
                # Brief delay then verify kill — don't leave ghost windows
                try:
                    import psutil as _ps2
                    norm_target = os.path.normpath(str(profile_dir)).replace("\\", "/").lower()
                    still_alive = False
                    for proc in _ps2.process_iter(["cmdline"]):
                        try:
                            cl = proc.info.get("cmdline")
                            if cl and norm_target in " ".join(cl).replace("\\", "/").lower():
                                still_alive = True
                                break
                        except Exception:
                            continue
                    if still_alive:
                        _kill_browsers_by_profile(str(profile_dir))
                except ImportError:
                    # Without psutil, still try kill
                    _kill_browsers_by_profile(str(profile_dir))
                except Exception:
                    pass
        except Exception:
            pass

    # Disk cleanup: this session's profile folder is never re-used, so delete it
    # now that the browser process is gone (runs last so nothing still holds files).
    try:
        _prof_dir = getattr(driver, "_seo_profile_dir", None)
        _prof_root = getattr(driver, "_seo_profile_root", None)
        if _prof_dir and _prof_root:
            remove_profile_dir(_prof_dir, _prof_root)
    except Exception:
        pass

    # Keep silenced at ERROR to avoid post-quit spam
    try:
        for _lg, _lvl in _silenced:
            if _lg.level != _logging.ERROR:
                _lg.setLevel(_logging.ERROR)
    except Exception:
        pass
    return closed