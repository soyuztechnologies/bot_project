"""
helpers.py

This module contains common helper functions that can be reused
across the entire automation project.
"""

import random
import time

from selenium.webdriver.common.action_chains import ActionChains

def build_fallback_keyword(original: str, extra: str | None) -> str | None:
    """
    Build a fallback keyword by appending only the missing words of
    ``extra`` to ``original`` (avoids "anubhav anubhav training" duplication).
    Returns None when no fallback is needed.
    """
    if not extra:
        return None
    extra = str(extra).strip()
    if not extra:
        return None
    original = str(original or "").strip()
    if not original:
        return extra
    if extra.lower() in original.lower():
        return None
    orig_words = set(original.lower().split())
    missing = [w for w in extra.split() if w.lower() not in orig_words]
    if not missing:
        return None
    fallback = (original + " " + " ".join(missing)).strip()
    if not fallback or fallback.lower() == original.lower():
        return None
    return fallback


def build_browser_mode(config: dict | None, browser_name: str | None = None) -> str:
    """
    Build the browser_mode string for the DB: headed/headless only
    (e.g. "Headless"). browser_name is accepted for signature compatibility
    but intentionally not stored.
    """
    _ = browser_name
    try:
        mode = str((config or {}).get("browser", {}).get("mode", "headed")).strip()
    except Exception:
        mode = "headed"
    if not mode:
        mode = "headed"
    return mode.capitalize()


def random_sleep(min_seconds: float, max_seconds: float, stop_event=None) -> None:
    """
    Sleep for a random duration.

    Args:
        min_seconds (float): Minimum sleep time.
        max_seconds (float): Maximum sleep time.
    """

    delay = random.uniform(min_seconds, max_seconds)

    if stop_event:
        stop_event.wait(delay)
    else:
        time.sleep(delay)


def human_typing(
    element, text: str, min_delay: float, max_delay: float, stop_event=None
) -> None:
    """
    Type text like a human.

    Args:
        element: Selenium input element.
        text (str): Text to type.
        min_delay (float): Minimum delay between characters.
        max_delay (float): Maximum delay between characters.
    """

    for char in text:
        if stop_event and stop_event.is_set():
            return

        element.send_keys(char)
        random_sleep(min_delay, max_delay, stop_event)


def press_enter(element) -> None:
    """
    Press Enter key.

    Args:
        element: Selenium element.
    """

    from selenium.webdriver.common.keys import Keys

    element.send_keys(Keys.RETURN)


def scroll_to_element(driver, element) -> None:
    """
    Scroll until the element is visible.

    Args:
        driver: Selenium WebDriver.
        element: Selenium element.
    """

    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)


def click_element(driver, element) -> None:
    """
    Click an element using JavaScript.

    Args:
        driver: Selenium WebDriver.
        element: Selenium element.
    """

    driver.execute_script("arguments[0].click();", element)


def scroll_and_click(driver, element, stop_event=None) -> None:
    """
    Scroll to an element and click it.
    """

    if stop_event and stop_event.is_set():
        return

    scroll_to_element(driver, element)

    if stop_event and stop_event.is_set():
        return

    random_sleep(1, 2, stop_event)

    if stop_event and stop_event.is_set():
        return

    click_element(driver, element)


def random_scroll(driver, min_scroll: int = 400, max_scroll: int = 1200) -> None:
    """
    Scroll to a random position.

    Args:
        driver: Selenium WebDriver.
        min_scroll (int): Minimum scroll distance.
        max_scroll (int): Maximum scroll distance.
    """

    scroll_position = random.randint(min_scroll, max_scroll)

    driver.execute_script(
    "window.scrollTo(0, arguments[0]);",
     scroll_position,
)


def simulate_human_reading(driver, stop_event=None) -> None:
    """
    Simulate human reading by scrolling slowly.

    Args:
        driver: Selenium WebDriver.
    """

    random_scroll(driver)

    random_sleep(3, 5, stop_event)

    random_scroll(driver)

    random_sleep(2, 4, stop_event)
