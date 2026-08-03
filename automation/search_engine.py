"""
search_engine.py

This module contains generic search engine functions.

Supported search engines:
- Google
- Bing
- Yahoo
- DuckDuckGo

All search engine settings are loaded from
data/search_engines.json.
"""
import base64
from utils.helpers import human_typing, press_enter, random_sleep, scroll_and_click
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

DEFAULT_TIMEOUT = 15


def get_by(strategy: str):
    """Return a Selenium By value from a config strategy name."""

    from selenium.webdriver.common.by import By

    try:
        return getattr(By, strategy)
    except AttributeError as error:
        raise ValueError(f"Unsupported locator strategy: {strategy}") from error


def wait_for_element(driver, locator: dict, timeout: int = DEFAULT_TIMEOUT):
    """Wait for one element described by a config locator."""

    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((get_by(locator["by"]), locator["value"]))
    )


def wait_for_elements(driver, locator: dict, timeout: int = DEFAULT_TIMEOUT):
    """Wait for elements described by a config locator."""

    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    return WebDriverWait(driver, timeout).until(
        EC.presence_of_all_elements_located((get_by(locator["by"]), locator["value"]))
    )


def build_search_url(engine: dict, keyword: str) -> str:
    """Build a direct search URL when the engine config provides a template."""

    url_template = engine.get("searchUrl")

    if not url_template:
        return ""

    return url_template.format(query=quote_plus(keyword))


def normalize_domain(domain: str) -> str:
    """Normalize a configured domain for host comparison."""

    parsed = urlparse(domain if "://" in domain else f"https://{domain}")
    hostname = parsed.hostname or domain

    return hostname.lower().removeprefix("www.")


def extract_result_url(href: str) -> str:
    """
    Extract the real destination URL from direct or wrapped result links.

    Supports:
    - Google
    - Bing
    - Yahoo
    - DuckDuckGo
    """

    if not href:
        return ""

    parsed = urlparse(href)

    if parsed.scheme not in {"http", "https"}:
        return ""

    query_values = parse_qs(parsed.query)

    # Google / Yahoo / DuckDuckGo
    for key in ("q", "url", "uddg"):
        value = query_values.get(key, [""])[0]

        if value.startswith(("http://", "https://")):
            return unquote(value)

    # Bing redirect URL
    u = query_values.get("u", [""])[0]

    if u:
        try:
            # Bing prefixes base64 string with "a1"
            if u.startswith("a1"):
                u = u[2:]

            # Fix missing padding
            u += "=" * (-len(u) % 4)

            decoded = base64.b64decode(u).decode("utf-8", errors="ignore")

            if decoded.startswith(("http://", "https://")):
                return decoded

        except Exception:
            pass

    # Already a direct URL
    return href


def is_target_url(url: str, target_domain: str) -> bool:
    """Return True when a URL belongs to the configured target domain."""

    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower().removeprefix("www.")
    target = normalize_domain(target_domain)

    return hostname == target or hostname.endswith(f".{target}")


def open_search_engine(driver, engine: dict) -> None:
    """
    Open the selected search engine.

    Args:
        driver: Selenium WebDriver.
        engine (dict): Search engine configuration.
    """

    driver.get(engine["url"])


def search_keyword(
    driver, engine: dict, keyword: str, config: dict, stop_event=None
) -> None:
    """
    Search a keyword.

    Args:
        driver: Selenium WebDriver.
        engine (dict): Search engine configuration.
        keyword (str): Keyword to search.
        config (dict): Global configuration.
    """

    direct_search_url = build_search_url(engine, keyword)

    if direct_search_url:
        driver.get(direct_search_url)
        random_sleep(
            config["timing"]["sleepMin"], config["timing"]["sleepMax"], stop_event
        )
        return

    locator = engine["searchBox"]
    search_box = wait_for_element(driver, locator)

    human_typing(
        search_box,
        keyword,
        config["timing"]["typingMin"],
        config["timing"]["typingMax"],
        stop_event,
    )

    if stop_event and stop_event.is_set():
        return

    press_enter(search_box)

    random_sleep(config["timing"]["sleepMin"], config["timing"]["sleepMax"], stop_event)


def next_page(driver, engine: dict, stop_event=None) -> bool:
    """
    Open the next search result page.

    Args:
        driver: Selenium WebDriver.
        engine (dict): Search engine configuration.

    Returns:
        bool: True if next page exists.
    """

    try:
        if "nextButton" not in engine:
            return False

        locator = engine["nextButton"]

        button = wait_for_element(driver, locator, timeout=5)

        scroll_and_click(driver, button, stop_event)
        random_sleep(1, 2, stop_event)

        return True

    except Exception:

        return False


def find_target_website(
    driver, engine: dict, target_domain: str, max_pages: int, stop_event=None
) -> bool:
    """
    Find the target website in search results.

    Args:
        driver: Selenium WebDriver.
        engine (dict): Search engine configuration.
        target_domain (str): Website domain.
        max_pages (int): Maximum pages to scan.

    Returns:
        bool
    """

    from selenium.common.exceptions import StaleElementReferenceException

    link_locator = engine["resultLinks"]
    open_target_mode = engine.get("openTarget", "direct")

    for page in range(max_pages):
        if stop_event and stop_event.is_set():
            return False

        try:
            links = wait_for_elements(driver, link_locator)
        except Exception:
            links = []

        for link in links:
            if stop_event and stop_event.is_set():
                return False

            try:
                href = extract_result_url(link.get_attribute("href"))
            except StaleElementReferenceException:
                continue

            if href and is_target_url(href, target_domain):
                print(f"Matched target URL: {href}")

                if open_target_mode == "direct":
                    driver.get(href)
                else:
                    try:
                        scroll_and_click(driver, link, stop_event)
                    except StaleElementReferenceException:
                        driver.get(href)
                    except Exception:
                        driver.get(href)

                return True

        if not next_page(driver, engine, stop_event):

            break

    return False
