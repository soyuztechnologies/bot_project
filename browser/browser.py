"""
browser.py
 
Browser setup and lifecycle helpers.
"""
 
import os
import shutil
import subprocess
import sys
import threading
 
from selenium.common.exceptions import WebDriverException
from seleniumbase import Driver
 
from utils.exceptions import (
    BrowserBinaryNotFoundError,
    BrowserStartupError,
    UnsupportedBrowserError,
)
 
 
_BROWSER_START_LOCK = threading.Lock()
 
 
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
 
    browsers = (
        config.get("browser", {}).get("browsers")
        or config.get("browser", {}).get("distribution")
        or []
    )
 
    if isinstance(browsers, str):
        browsers = [browsers]
 
    for browser in browsers:
        browser = str(browser).lower().strip()
 
        try:
            if browser == "chrome":
                result = subprocess.run(
                    ["python", "-m", "seleniumbase", "install", "uc_driver"],
                    capture_output=True, text=True, check=False,
                )
                if result.returncode != 0:
                    raise BrowserStartupError(f"uc_driver install failed: {result.stderr[:300]}", browser=browser)
            elif browser == "edge":
                result = subprocess.run(
                    ["python", "-m", "seleniumbase", "install", "edgedriver"],
                    capture_output=True, text=True, check=False,
                )
                if result.returncode != 0:
                    raise BrowserStartupError(f"edgedriver install failed: {result.stderr[:300]}", browser=browser)
            elif browser == "firefox":
                result = subprocess.run(
                    ["python", "-m", "seleniumbase", "install", "geckodriver"],
                    capture_output=True, text=True, check=False,
                )
                if result.returncode != 0:
                    raise BrowserStartupError(f"geckodriver install failed: {result.stderr[:300]}", browser=browser)
            elif browser in ("opera", "brave"):
                result = subprocess.run(
                    ["python", "-m", "seleniumbase", "install", "chromedriver"],
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
 
 
def setup_browser(config, browser_name):
    """
    Start and configure a browser instance.
    """
 
    browser_name = str(browser_name).lower().strip()
 
    browser_config = config.get("browser", {})
 
    headless = browser_config.get("headless", False) or (str(browser_config.get("mode", "")).lower() == "headless")
    maximize = browser_config.get("maximize", True)
    # In headless, maximizing is no-op and can cause errors on some drivers
    if headless:
        maximize = False
 
    thread_id = threading.get_ident()
 
    profile_root = browser_config.get(
        "profile_dir",
        os.path.join(os.getcwd(), "browser_profiles"),
    )
 
    profile_path = os.path.join(
        profile_root,
        f"{browser_name}_{thread_id}",
    )
 
    try:
        os.makedirs(profile_path, exist_ok=True)
    except OSError as e:
        raise BrowserStartupError(f"Failed to create profile dir {profile_path}: {e}", browser=browser_name, cause=e) from e
 
    with _BROWSER_START_LOCK:
 
        try:
            if browser_name == "chrome":
 
                driver = Driver(
                    browser="chrome",
                    uc=True,
                    user_data_dir=profile_path,
                    headless=headless,
                    chromium_arg=get_chromium_args(),
                )
 
            elif browser_name == "edge":
 
                driver = Driver(
                    browser="edge",
                    uc=True,
                    user_data_dir=profile_path,
                    headless=headless,
                    chromium_arg=get_chromium_args(),
                )
 
            elif browser_name == "firefox":
 
                driver = Driver(
                    browser="firefox",
                    uc=False,
                    headless=headless,
                    user_data_dir=profile_path,
                    firefox_pref="media.volume_scale=0.0",
                )
 
            elif browser_name == "opera":
 
                driver = Driver(
                    browser="opera",
                    uc=False,
                    user_data_dir=profile_path,
                    headless=headless,
                    chromium_arg=get_chromium_args(),
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
                )
 
            else:
                raise UnsupportedBrowserError(
                    f"Unsupported browser: {browser_name}", browser=browser_name
                )
        except (BrowserBinaryNotFoundError, UnsupportedBrowserError):
            raise
        except WebDriverException as e:
            raise BrowserStartupError(f"Browser startup failed for {browser_name}: {e}", browser=browser_name, cause=e) from e
        except Exception as e:
            raise BrowserStartupError(f"Browser startup failed for {browser_name}: {e}", browser=browser_name, cause=e) from e
 
    if maximize:
        try:
            driver.maximize_window()
        except WebDriverException as e:
            import logging as _logging
            _logging.getLogger(__name__).warning(f"Maximize failed for {browser_name}: {e}", exc_info=False)
        except Exception as e:
            import logging as _logging
            _logging.getLogger(__name__).warning(f"Maximize unexpected error for {browser_name}: {e}", exc_info=False)
 
    return driver
 
 
def close_browser(driver):
    """
    Safely close browser instance.
    """
 
    if driver is None:
        return
 
    try:
        driver.quit()
    except WebDriverException as e:
        import logging as _logging
        _logging.getLogger(__name__).warning(f"Browser quit WebDriverException: {e}", exc_info=False)
    except Exception as e:
        import logging as _logging
        _logging.getLogger(__name__).warning(f"Browser quit unexpected error: {e}", exc_info=False)