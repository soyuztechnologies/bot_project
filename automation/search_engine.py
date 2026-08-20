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
from selenium.webdriver.common.by import By
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
    driver,
    engine: dict,
    keyword: str,
    config: dict,
    stop_event=None,
) -> None:
    """
    Search a keyword by typing it into the search box.

    The keyword is typed character-by-character instead of
    navigating directly to a generated search URL.

    This function is used by the search-engine-first flow.
    """

    if stop_event and stop_event.is_set():
        return

    locator = engine.get("searchBox")

    if not locator:
        raise ValueError(
            "Search box configuration not found."
        )

    print(
        f"Typing keyword into search box : {keyword}"
    )

    # ---------------------------------------------------------
    # Find search box
    # ---------------------------------------------------------

    search_box = wait_for_element(
        driver,
        locator,
        timeout=15,
    )

    if stop_event and stop_event.is_set():
        return

    # ---------------------------------------------------------
    # Make sure the search box is ready
    # ---------------------------------------------------------

    try:
        search_box.click()
    except Exception:
        pass

    if stop_event and stop_event.is_set():
        return

    # ---------------------------------------------------------
    # Type keyword gradually
    # ---------------------------------------------------------

    human_typing(
        search_box,
        keyword,
        config["timing"]["typingMin"],
        config["timing"]["typingMax"],
        stop_event,
    )

    if stop_event and stop_event.is_set():
        return

    print(
        f"Keyword typed : {keyword}"
    )

    # ---------------------------------------------------------
    # Submit search
    # ---------------------------------------------------------

    press_enter(search_box)

    if stop_event and stop_event.is_set():
        return

    # ---------------------------------------------------------
    # Wait for search results
    # ---------------------------------------------------------

    random_sleep(
        config["timing"]["sleepMin"],
        config["timing"]["sleepMax"],
        stop_event,
    )

    print(
        f"Search submitted : {keyword}"
    )


def is_google_verification_page(driver):
    """
    Detect an actual Google verification / CAPTCHA page.

    Avoids scanning the complete HTML source because normal
    Google pages can contain CAPTCHA-related scripts/text.
    """

    try:
        current_url = driver.current_url.lower()
        page_title = driver.title.lower()

        visible_text = driver.find_element(
            "tag name",
            "body"
        ).text.lower()

        # Strong URL indicators
        url_indicators = [
            "/sorry/",
        ]

        # Strong visible-page indicators
        text_indicators = [
            "unusual traffic",
            "our systems have detected unusual traffic",
            "i'm not a robot",
            "verify you are human",
        ]

        if any(
            indicator in current_url
            for indicator in url_indicators
        ):
            return True

        if any(
            indicator in page_title
            for indicator in text_indicators
        ):
            return True

        if any(
            indicator in visible_text
            for indicator in text_indicators
        ):
            return True

        return False

    except Exception:
        return False


def open_video_tab(
    driver,
    engine: dict,
    config: dict,
    stop_event=None,
) -> bool:
    """
    Open the Videos tab from the current search-engine results page.

    Returns:
        bool: True when the Videos tab was opened successfully.
    """

    if stop_event and stop_event.is_set():
        return False

    video_tab = engine.get("videoTab")

    print(
    f"Video tab locator : {video_tab}"
)

    if not video_tab:
        print("Video tab configuration not found.")
        return False

    try:
        print("Opening Videos tab...")

        # ---------------------------------------------
        # Google verification / CAPTCHA detection
        # ---------------------------------------------
        if is_google_verification_page(driver):
            print(
                "[SEARCH ENGINE] Verification page detected."
            )
            print(
                "[SEARCH ENGINE] Skipping Videos tab for this attempt."
            )
            return False

        # ---------------------------------------------
        # Find Videos tab
        # ---------------------------------------------
        tab = wait_for_element(
            driver,
            video_tab,
            timeout=10,
        )

        print("Videos tab element found successfully.")

        if stop_event and stop_event.is_set():
            return False

        # ---------------------------------------------
        # Check again before clicking
        # ---------------------------------------------
        if is_google_verification_page(driver):
            print(
                "[SEARCH ENGINE] Verification page detected "
                "before Videos tab click."
            )
            return False

        old_windows = driver.window_handles

        print("About to click Videos tab...")

        scroll_and_click(
            driver,
            tab,
            stop_event,
        )

        

        random_sleep(
            config["timing"]["sleepMin"],
            config["timing"]["sleepMax"],
            stop_event,
        )

        new_windows = driver.window_handles

        if len(new_windows) > len(old_windows):

            for window in new_windows:

                if window not in old_windows:

                    driver.switch_to.window(window)

                    print(
                      "[SEARCH ENGINE] Switched to "
                      "new Videos tab."
                    )

                    break

        if stop_event and stop_event.is_set():
            return False

        print("Videos tab opened successfully.")

        return True

    except Exception as error:

        # ---------------------------------------------
        # Verification may have appeared while waiting
        # ---------------------------------------------
        if is_google_verification_page(driver):
            print(
                "[SEARCH ENGINE] Verification page detected "
                "while opening Videos tab."
            )
            return False

        print(
            f"Failed to open Videos tab : {error}"
        )

        return False

def normalize_youtube_video_url(url: str) -> str:
    """
    Return a canonical YouTube watch URL.

    Removes timestamp and other query parameters so the
    same video is not processed multiple times.
    """

    if not url:
        return ""

    parsed = urlparse(url)

    hostname = (
        parsed.hostname or ""
    ).lower().removeprefix("www.")

    if hostname not in {
        "youtube.com",
        "m.youtube.com",
    }:  
        return url

    query_values = parse_qs(parsed.query)

    video_id = query_values.get("v", [""])[0].strip()

    if not video_id:
        return url

    return f"https://www.youtube.com/watch?v={video_id}"

def gradual_scroll_search_results(
    driver,
    stop_event=None,
):
    """
    Gradually scroll the Google Videos results page.

    The scroll is intentionally incremental so that the page
    is inspected progressively instead of jumping directly
    to a target result.
    """

    if stop_event and stop_event.is_set():
        return False

    try:
        current_position = driver.execute_script(
            "return window.pageYOffset;"
        )

        viewport_height = driver.execute_script(
            "return window.innerHeight;"
        )

        document_height = driver.execute_script(
            "return document.body.scrollHeight;"
        )

        if current_position + viewport_height >= document_height - 50:
            print("Reached bottom of current results page.")
            return False

        # Small progressive scroll.
        scroll_amount = max(
            250,
            min(500, int(viewport_height * 0.55))
        )

        driver.execute_script(
            "window.scrollBy({top: arguments[0], behavior: 'smooth'});",
            scroll_amount,
        )

        # Give the page time to complete the scroll/load.
        random_sleep(
            1.0,
            2.0,
            stop_event,
        )

        return True

    except Exception as error:

        print(
            f"Unable to scroll search results : {error}"
        )

        return False

def find_target_video_in_video_results(
    driver,
    engine: dict,
    target_channel: str,
    max_pages: int,
    stop_event=None,
    youtube_config: dict = None,
) -> bool:
    """
    Find the target-channel YouTube result on the
    search-engine Videos results page.

    The page is inspected progressively while scrolling.
    No arbitrary YouTube result is opened.
    """

    from selenium.common.exceptions import (
        StaleElementReferenceException,
    )
    from selenium.webdriver.common.by import By

    video_locator = engine.get("videoResultLinks")
    channel_result_locator = engine.get("videoResultChannel")
    

    print(
        f"Video result channel selector configured : "
        f"{bool(channel_result_locator)}"
    )

    if not video_locator:
        print("Video result configuration not found.")
        return False

    if not target_channel:
        print("Target channel not configured.")
        return False

    target = " ".join(
        target_channel.strip().lower().split()
    )

    # Prevent inspecting the same result repeatedly
    inspected_urls = set()

    for page in range(max_pages):

        if stop_event and stop_event.is_set():
            return False

        print(
            f"Checking video results page "
            f"{page + 1}/{max_pages}..."
        )

        page_target_found = False

        # ---------------------------------------------------------
        # Progressively inspect the current Google Videos page
        # ---------------------------------------------------------

        for scroll_attempt in range(20):

            if stop_event and stop_event.is_set():
                return False

            # -----------------------------------------------------
            # Read currently available result links
            # -----------------------------------------------------

            # try:

            #     links = wait_for_elements(
            #         driver,
            #         video_locator,
            #         timeout=5,
            #     )

            # except Exception:

            #     links = []

            try:
                print(
                     f"Video result locator : "
                     f"{video_locator}"
                )

                result_timeout = 15 if engine.get("isDuckDuckGo") else 5

                links = wait_for_elements(
                    driver,
                    video_locator,
                    timeout=result_timeout,
                )

                print(
                    f"wait_for_elements returned : "
                    f"{len(links)}"
                )

            except Exception as error:

                print(
                    f"VIDEO RESULT LOCATOR ERROR : "
                    f"{error}"
                )

                links = []

                print(
                     f"Visible video result elements : "
                     f"{len(links)}"
                )

            # -----------------------------------------------------
            # Inspect current results
            # -----------------------------------------------------

            for index, link in enumerate(
                links,
                start=1,
            ):

                if stop_event and stop_event.is_set():
                    return False

                try:

                    # -------------------------------------------------
                    # Result URL
                    # -------------------------------------------------

                    href = (
                        link.get_attribute("href")
                        or link.get_attribute("ourl")
                        or ""
                    ).strip()

                    if not href:
                        continue

                    # Avoid processing the same Google result
                    # again after the page scrolls.
                    if href in inspected_urls:
                        continue

                    inspected_urls.add(href)

                    # -------------------------------------------------
                    # Result title
                    # -------------------------------------------------

                    title = (
                        link.text
                        or ""
                    ).strip()

                    normalized_title = " ".join(
                        title.split()
                    )

                    # -------------------------------------------------
                    # Find Google result card
                    # -------------------------------------------------
                    result_card = None

                    try:

                        # Bing result card has an "ourl" attribute
                        if link.get_attribute("ourl"):
                            result_card = link

                        elif engine.get("isDuckDuckGo"):
                           # DuckDuckGo: the <a> itself contains the complete result card
                           result_card = link

                           spans = result_card.find_elements(
                                  By.CSS_SELECTOR,
                                  "span"
                                  )

                           for span in spans:
                                text = (span.text or "").strip()
                                if text:
                                  print(f"DDG SPAN: {text}")

                        elif link.get_attribute("data-referenceurl"):
                             # Yahoo: the <a> itself contains the complete video card
                             result_card = link

                        else:
                             # Google result card
                             result_card = link.find_element(
                                    By.XPATH,
                                    "./ancestor::div[.//*[@aria-label and contains(@aria-label, 'on YouTube')]][1]"
                            )

                    except Exception:
                        result_card = None
                        pass
                    # -------------------------------------------------
                    # Read complete card text
                    # -------------------------------------------------

                    card_text = ""

                    if result_card:

                        try:

                            card_text = (
                                result_card.text
                                or ""
                            ).strip()

                            print(f"DEBUG CARD TEXT: {card_text}")

                        except Exception:

                            card_text = ""

                    normalized_card_text = " ".join(
                        card_text.split()
                    )

                    # -------------------------------------------------
                    # Read ARIA metadata
                    # -------------------------------------------------

                    card_aria = ""

                    if result_card:

                        try:

                            aria_elements = (
                                result_card.find_elements(
                                    By.XPATH,
                                    ".//*[@aria-label]"
                                )
                            )

                            for aria_element in aria_elements:

                                aria_value = (
                                    aria_element.get_attribute(
                                        "aria-label"
                                    )
                                    or ""
                                ).strip()

                                if not aria_value:
                                    continue

                                aria_lower = (
                                    aria_value.lower()
                                )

                                if (
                                    " by " in aria_lower
                                    and " on youtube" in aria_lower
                                ):

                                    card_aria = aria_value

                                    break

                        except Exception:

                            pass

                    # -------------------------------------------------
                    # Print result information
                    # -------------------------------------------------

                    print(
                        f"[RESULT] "
                        f"{normalized_title[:150]}"
                    )

                    if card_aria:

                        print(
                            f"[RESULT] Channel metadata : "
                            f"{card_aria[:220]}"
                        )

                    # -------------------------------------------------
                    # Target channel verification
                    # -------------------------------------------------

                    channel_match = False

                    if card_aria:

                        aria_normalized = " ".join(
                            card_aria.lower().split()
                        )

                        if target in aria_normalized:

                            channel_match = True

                    # -------------------------------------------------
                    # Fallback to complete result-card text
                    # -------------------------------------------------

                    if (
                        not channel_match
                        and normalized_card_text
                    ):

                        card_normalized = " ".join(
                            normalized_card_text.lower().split()
                        )

                        print(
                            f"TARGET CHECK: target='{target}' | "
                            f"found={target in card_normalized}"
                        )

                        if target in card_normalized:

                            channel_match = True

                    # -------------------------------------------------
                    # Target found
                    # -------------------------------------------------

                    if channel_match:

                        print()
                        print("=" * 60)

                        print(
                            "TARGET RESULT FOUND"
                        )

                        print(
                            f"Target channel : "
                            f"{target_channel}"
                        )

                        print(
                            f"Result title : "
                            f"{normalized_title}"
                        )

                        print(
                            f"Result URL : "
                            f"{href}"
                        )

                        if card_aria:

                            print(
                                f"Result metadata : "
                                f"{card_aria}"
                            )

                        print("=" * 60)

                        # Store ONLY the validated URL.
                        if link.get_attribute("data-referenceurl"):
                          driver.target_video_url = (
                                link.get_attribute("data-referenceurl")
                                or href
                           )
                        else:
                            driver.target_video_url = href

                        page_target_found = True

                        break

                except StaleElementReferenceException:

                    continue

                except Exception as error:

                    print(
                        f"Unable to inspect result : "
                        f"{error}"
                    )

                    continue

            # -----------------------------------------------------
            # Target found
            # -----------------------------------------------------

            if page_target_found:

                print(
                    f"Target result identified on "
                    f"page {page + 1}."
                )

                return True

            # -----------------------------------------------------
            # Gradual scroll
            # -----------------------------------------------------

            print(
                f"Scrolling search results "
                f"({scroll_attempt + 1}/20)..."
            )

            moved = gradual_scroll_search_results(
                driver,
                stop_event,
            )

            if not moved:

                print(
                    "Reached end of current search-results page."
                )

                break

        # ---------------------------------------------------------
        # Current Google page exhausted
        # ---------------------------------------------------------

        print(
            f"Target result not identified on "
            f"page {page + 1}."
        )

        # ---------------------------------------------------------
        # Move to next Google Videos page
        # ---------------------------------------------------------

        if page < max_pages - 1:

            if stop_event and stop_event.is_set():
                return False

            try:

                moved = next_page(
                    driver,
                    engine,
                    stop_event,
                )

            except Exception as error:

                print(
                    f"Unable to open next results page : "
                    f"{error}"
                )

                moved = False

            if not moved:

                print(
                    "No more search result pages available."
                )

                break

    # -------------------------------------------------------------
    # Target not found anywhere
    # -------------------------------------------------------------

    print(
        f"Target channel video not found : "
        f"{target_channel}"
    )

    return False


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
