"""
browser.py
 
This module is responsible for:
1. Launching the browser.
2. Applying browser options.
3. Closing the browser safely.
"""

import threading
from pathlib import Path
from seleniumbase import Driver

_BROWSER_START_LOCK = threading.Lock()
PROJECT_DIR = Path(__file__).resolve().parents[1]


def setup_browser(config: dict):
    """
    Create and return a Chrome browser instance.
 
    Args:
        config (dict): Browser configuration from config.json.
 
    Returns:
        seleniumbase Driver instance.
    """
    with _BROWSER_START_LOCK:

     if config["browser"].get("mode") == "headless":
        driver = Driver(
            uc=True,
            headless=True,
            chromium_arg="--mute-audio"
        )

     else:
        driver = Driver(
            uc=True,
            headless=False,
            chromium_arg="--mute-audio"
        )   
       
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