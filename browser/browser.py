"""
browser.py
 
This module is responsible for:
1. Launching the browser.
2. Applying browser options.
3. Closing the browser safely.
"""

import threading
import os
import shutil
from seleniumbase import Driver

_BROWSER_START_LOCK = threading.Lock()

def get_brave_binary():
    """
    Find Brave browser executable.
    Works on both Windows and Linux/Docker.
    """

    # Docker / Linux
    linux_path = shutil.which("brave-browser")

    if linux_path:
        return linux_path

    # Environment variable, if explicitly provided
    env_path = os.getenv("BRAVE_BINARY")

    if env_path and os.path.exists(env_path):
        return env_path

    # Windows local development
    windows_paths = [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
    ]

    for path in windows_paths:
        if os.path.exists(path):
            return path

    raise FileNotFoundError(
        "Brave browser executable was not found."
    )


def setup_browser(config: dict, browser_name):
    """
    Create and return a browser instance.
    """

    headless = config["browser"].get("mode") == "headless"

    with _BROWSER_START_LOCK:

        print(f"[{browser_name.upper()}] Launching browser...")

        if browser_name == "chrome":

            driver = Driver(
                browser="chrome",
                uc=True,
                headless=headless,
                chromium_arg="--mute-audio",
            )

        elif browser_name == "edge":

            driver = Driver(
                browser="edge",
                headless=headless,
            )

        elif browser_name == "firefox":

            driver = Driver(
                browser="firefox",
                headless=headless,
            )

        elif browser_name == "opera":

            driver = Driver(
                browser="opera",
                headless=headless,
            )

        elif browser_name == "brave":

            brave_binary = get_brave_binary()

            print(f"[BRAVE] Using browser: {brave_binary}")

            driver = Driver(
                 browser="chrome",
                 headless=headless,
                 binary_location=brave_binary,
            )

        else:
            raise ValueError(
                f"Unsupported browser: {browser_name}"
            )

        print(f"[{browser_name.upper()}] Browser launched.")

    if config["browser"].get("maximize", True):

        try:
            driver.maximize_window()
            print(f"[{browser_name.upper()}] Browser maximized.")

        except Exception as error:
            print(
                f"[{browser_name.upper()}] Maximize failed : {error}"
            )

    return driver
 
 
def close_browser(driver):
    """
    Close browser safely.
    """

    if not driver:
        return

    browser_name = "unknown"

    try:
        browser_name = driver.capabilities.get(
            "browserName",
            "unknown"
        )

        print(f"[{browser_name.upper()}] Closing browser...")

        driver.quit()

        print(
            f"[{browser_name.upper()}] Browser driver quit completed."
        )

    except Exception as error:

        print(
            f"[{browser_name.upper()}] Browser close error : {error}"
        )