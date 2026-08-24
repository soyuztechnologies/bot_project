"""
browser.py

Responsible for:

1. Preparing required browser drivers.
2. Launching supported browsers.
3. Applying browser-specific options.
4. Keeping audio muted.
5. Closing browsers safely.
"""

import os
import traceback
import shutil
import subprocess
import sys
import threading

from seleniumbase import Driver

_BROWSER_START_LOCK = threading.Lock()


# ---------------------------------------------------------
# Brave
# ---------------------------------------------------------

def get_brave_binary():
    """
    Find Brave browser executable.
    Works on Windows and Linux/Docker.
    """

    linux_path = shutil.which("brave-browser")

    if linux_path:
        return linux_path

    env_path = os.getenv("BRAVE_BINARY")

    if env_path and os.path.exists(env_path):
        return env_path

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


# ---------------------------------------------------------
# Driver Preparation
# ---------------------------------------------------------

def prepare_browser_drivers(config):
    """
    Prepare all required WebDrivers before worker threads start.

    This prevents multiple worker threads from trying to
    download/update the same driver simultaneously.
    """

    browsers = config["browser"].get(
        "browsers",
        ["chrome"]
    )

    distribution = config["browser"].get(
        "distribution",
        {}
    )

    # Use browsers from distribution when available.
    if distribution:
        browsers = list(distribution.keys())

    browsers = [
        browser.lower()
        for browser in browsers
    ]

    print("\n" + "=" * 60)
    print("Preparing Browser Drivers")
    print("=" * 60)

    required_drivers = set()

    for browser in browsers:

        if browser == "chrome":

            # Chrome uses UC mode in this project.
            required_drivers.add("uc_driver")

        elif browser == "edge":

            required_drivers.add("edgedriver")

        elif browser == "firefox":

            required_drivers.add("geckodriver")

        elif browser == "opera":

            # Opera uses Chromium/WebDriver.
            required_drivers.add("chromedriver")

        elif browser == "brave":

            # Brave uses Chromium WebDriver in this project.
            required_drivers.add("chromedriver")

        else:

            raise ValueError(
                f"Unsupported browser in configuration: {browser}"
            )

    for driver_name in sorted(required_drivers):

        print(
            f"\n[DRIVER] Preparing {driver_name}..."
        )

        try:

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "seleniumbase",
                    "get",
                    driver_name,
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:

                print(result.stdout)
                print(result.stderr)

                raise RuntimeError(
                    f"Failed to prepare {driver_name}."
                )

            print(
                f"[DRIVER] {driver_name} ready."
            )

        except Exception as error:

            raise RuntimeError(
                f"Driver preparation failed for "
                f"{driver_name}: {error}"
            ) from error

    print("\n" + "=" * 60)
    print("All Required Browser Drivers Ready")
    print("=" * 60)


# ---------------------------------------------------------
# Chromium Arguments
# ---------------------------------------------------------

def get_chromium_args():
    """
    Common Chromium arguments.

    Keeps audio muted in Chromium-based browsers.
    """

    return ",".join([
        "--mute-audio",
        "--disable-notifications",
    ])


# ---------------------------------------------------------
# Browser Setup
# ---------------------------------------------------------

def setup_browser(config: dict, browser_name: str):
    """
    Create and return a browser instance.
    """

    headless = (
        config["browser"].get("mode") == "headless"
    )

    browser_name = browser_name.lower()

    # -----------------------------------------------------
    # Persistent browser profile
    # -----------------------------------------------------

    profile_path = os.path.abspath(
        os.path.join(
            "profiles",
            browser_name,
            f"thread_{threading.get_ident()}",
        )
    )

    os.makedirs(profile_path, exist_ok=True)

    print(
        f"[{browser_name.upper()}] Profile : {profile_path}"
    )

    print(
        f"[{browser_name.upper()}] Launching browser..."
    )

    with _BROWSER_START_LOCK:

        # -----------------------------------------------------
        # Chrome
        # -----------------------------------------------------

        if browser_name == "chrome":

            driver = Driver(
                browser="chrome",
                uc=False,
                user_data_dir=profile_path,
                headless=headless,
                chromium_arg=get_chromium_args(),
            )

        # -----------------------------------------------------
        # Edge
        # -----------------------------------------------------

        elif browser_name == "edge":

            driver = Driver(
                browser="edge",
                uc=False,
                user_data_dir=profile_path,
                headless=headless,
            )

        # -----------------------------------------------------
        # Firefox
        # -----------------------------------------------------

        elif browser_name == "firefox":
            driver = Driver(
                browser="firefox",
                uc=False,
                headless=headless,
            )

        # -----------------------------------------------------
        # Opera
        # -----------------------------------------------------

        elif browser_name == "opera":
            driver = Driver(
                browser="chrome",
                binary_location="/usr/bin/opera",
                uc=False,
                headless=headless,
                no_sandbox=True,
                disable_gpu=True,
                user_data_dir=profile_path,
                chromium_arg=get_chromium_args(),
            )
        # -----------------------------------------------------
        # Brave
        # -----------------------------------------------------

        elif browser_name == "brave":

            brave_binary = get_brave_binary()

            print(
                f"[BRAVE] Using browser: {brave_binary}"
            )

            driver = Driver(
                browser="chrome",
                binary_location=brave_binary,
                uc=False,
                user_data_dir=profile_path,
                headless=headless,
                chromium_arg=get_chromium_args(),
            )

        else:

            raise ValueError(
                f"Unsupported browser: {browser_name}"
            )

        print(
            f"[{browser_name.upper()}] Browser launched."
        )

    # -----------------------------------------------------
    # Opera - deny geolocation permission
    # -----------------------------------------------------

    if browser_name == "opera":

      try:
        driver.execute_cdp_cmd(
            "Browser.setPermission",
            {
                "permission": {
                    "name": "geolocation"
                },
                "setting": "denied",
                "origin": "https://www.google.com",
            },
        )

        print(
            "[OPERA] Geolocation permission denied."
        )

      except Exception as error:

        print(
            f"[OPERA] Geolocation permission setup failed : {error}"
        )

    # -----------------------------------------------------
    # Maximize
    # -----------------------------------------------------

    if config["browser"].get("maximize", True):

        try:

            driver.maximize_window()

            print(
                f"[{browser_name.upper()}] "
                f"Browser maximized."
            )

        except Exception as error:

            print(
                f"[{browser_name.upper()}] "
                f"Maximize failed : {error}"
            )

    return driver

# ---------------------------------------------------------
# Close Browser
# ---------------------------------------------------------

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

        print(
            f"[{browser_name.upper()}] "
            f"Closing browser..."
        )

        driver.quit()

        print(
            f"[{browser_name.upper()}] "
            f"Browser driver quit completed."
        )

    except Exception as error:

        print(
            f"[{browser_name.upper()}] "
            f"Browser close error : {error}"
        )