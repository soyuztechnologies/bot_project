"""
browser.py

Browser setup and lifecycle helpers.
"""

import os
import shutil
import subprocess
import sys
import threading

from seleniumbase import Driver


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
                subprocess.run(
                    ["python", "-m", "seleniumbase", "install", "uc_driver"],
                    check=False,
                )

            elif browser == "edge":
                subprocess.run(
                    ["python", "-m", "seleniumbase", "install", "edgedriver"],
                    check=False,
                )

            elif browser == "firefox":
                subprocess.run(
                    ["python", "-m", "seleniumbase", "install", "geckodriver"],
                    check=False,
                )

            elif browser in ("opera", "brave"):
                subprocess.run(
                    ["python", "-m", "seleniumbase", "install", "chromedriver"],
                    check=False,
                )

        except Exception:
            pass


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

    headless = browser_config.get("headless", False)
    maximize = browser_config.get("maximize", True)

    thread_id = threading.get_ident()

    profile_root = browser_config.get(
        "profile_dir",
        os.path.join(os.getcwd(), "browser_profiles"),
    )

    profile_path = os.path.join(
        profile_root,
        f"{browser_name}_{thread_id}",
    )

    os.makedirs(profile_path, exist_ok=True)

    with _BROWSER_START_LOCK:

        if browser_name == "chrome":

            driver = Driver(
                browser="chrome",
                uc=True,
                user_data_dir=profile_path,
                headless=False,
                chromium_arg=get_chromium_args(),
            )

        elif browser_name == "edge":

            driver = Driver(
                browser="edge",
                uc=True,
                user_data_dir=profile_path,
                headless=False,
                chromium_arg=get_chromium_args(),
            )

        elif browser_name == "firefox":

            driver = Driver(
                browser="firefox",
                uc=False,
                headless=headless,
                firefox_pref="media.volume_scale=0.0",
            )

        elif browser_name == "opera":

            driver = Driver(
                browser="opera",
                uc=False,
                user_data_dir=profile_path,
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
            except Exception:
                pass

        elif browser_name == "brave":

            brave_binary = get_brave_binary()

            if not brave_binary:
                raise FileNotFoundError(
                    "Brave browser binary was not found."
                )

            driver = Driver(
                browser="chrome",
                binary_location=brave_binary,
                uc=True,
                user_data_dir=profile_path,
                headless=False,
                chromium_arg=get_chromium_args(),
            )

        else:
            raise ValueError(
                f"Unsupported browser: {browser_name}"
            )

    if maximize:
        try:
            driver.maximize_window()
        except Exception:
            pass

    return driver


def close_browser(driver):
    """
    Safely close browser instance.
    """

    if driver is None:
        return

    try:
        driver.quit()
    except Exception:
        pass