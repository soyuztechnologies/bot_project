"""
browser.py

This module is responsible for:
1. Launching the browser.
2. Applying browser options.
3. Closing the browser safely.
"""

import platform
import subprocess
import threading
from pathlib import Path


_BROWSER_START_LOCK = threading.Lock()
PROJECT_DIR = Path(__file__).resolve().parents[1]


def detect_chrome_major_version(config: dict):
    """
    Detect the installed Chrome major version for undetected-chromedriver.

    Args:
        config (dict): Project configuration from config.json.

    Returns:
        int | None: Chrome major version, or None when it cannot be detected.
    """

    configured_version = config["browser"].get("versionMain")

    if configured_version:
        return int(configured_version)

    if platform.system() != "Windows":
        return None

    chrome_paths = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ]

    for chrome_path in chrome_paths:
        if not chrome_path.exists():
            continue

        command = (
            f"(Get-Item '{chrome_path}').VersionInfo.ProductVersion"
        )

        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )

        version = result.stdout.strip()

        if version:
            return int(version.split(".", 1)[0])

    return None


def setup_browser(config: dict):
    """
    Create and return a Chrome browser instance.

    Args:
        config (dict): Browser configuration from config.json.

    Returns:
        webdriver.Chrome: Chrome browser instance.
    """

    try:
        import undetected_chromedriver as uc
        from selenium.webdriver.chrome.options import Options
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "Browser dependencies are missing. Install them with: "
            "pip install -r requirements.txt"
        ) from error

    if not getattr(uc.Chrome, "_seo_bot_safe_del", False):
        original_del = uc.Chrome.__del__

        def safe_del(driver):
            try:
                original_del(driver)
            except Exception:
                pass

        uc.Chrome.__del__ = safe_del
        uc.Chrome._seo_bot_safe_del = True

    options = Options()

    # Enable headless mode if configured
    if config["browser"].get("mode") == "headless":
        options.add_argument("--headless=new")

    # Disable automation info bar
    options.add_argument("--disable-blink-features=AutomationControlled")

    # Disable browser notifications
    options.add_argument("--disable-notifications")

    # Disable popup blocking
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")

    # Start browser
    chrome_version = detect_chrome_major_version(config)
    driver_cache_path = PROJECT_DIR / ".drivers"
    driver_cache_path.mkdir(exist_ok=True)
    uc.Patcher.data_path = str(driver_cache_path)

    driver_kwargs = {
        "options": options,
        "patcher_force_close": False,
        "use_subprocess": True,
        "user_multi_procs": False,
    }

    if chrome_version:
        driver_kwargs["version_main"] = chrome_version

    with _BROWSER_START_LOCK:
        driver = uc.Chrome(**driver_kwargs)

    # Maximize browser if enabled
    if config["browser"].get("maximize", True):
        driver.maximize_window()

    return driver


def close_browser(driver):
    """
    Close browser safely.

    Args:
        driver: Selenium WebDriver instance.
    """

    if driver:
        try:
            driver.quit()
        except Exception:
            pass
