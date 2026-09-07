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
from selenium.webdriver.common.keys import Keys
import logging
import time
from selenium.common.exceptions import (
    InvalidSelectorException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from utils.helpers import human_typing, press_enter, random_sleep, scroll_and_click
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
 
from utils.exceptions import (
    BrowserDiedError,
    CaptchaDetectedError,
    EngineConfigError,
    EngineOpenError,
    InvalidLocatorError,
    NavigationError,
    SearchFailedError,
    TargetNotFoundError,
    UnhandledAutomationError,
    wrap_unexpected,
)
 
logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15


def _short_err(e, max_len=220) -> str:
    """Return concise exception summary without uc_driver stacktrace dump."""
    try:
        text = str(e)
        if not text or not text.strip():
            return type(e).__name__
        for line in text.splitlines():
            s = line.strip()
            if not s:
                continue
            # Strip repeated "Message:" prefix (Selenium nests it: "Message: Message: \nStacktrace:")
            tmp = s
            low_tmp = tmp.lower()
            # iteratively strip Message: prefix
            while low_tmp.startswith("message:"):
                tmp = tmp[len("message:"):].strip()
                low_tmp = tmp.lower()
                if not tmp:
                    break
            if not tmp:
                continue
            s = tmp
            low = s.lower()
            if low in ("message:", "stacktrace:") or low.startswith("stacktrace"):
                continue
            # Skip raw stack frames
            if "GetHandleVerifier" in s or s.startswith("uc_driver") or s.startswith("KERNEL32") or s.startswith("ntdll"):
                continue
            if low.startswith("uc_driver"):
                continue
            if len(s) > max_len:
                s = s[:max_len].rstrip() + "…"
            return s if s else type(e).__name__
        return type(e).__name__
    except Exception:
        try:
            return str(e).splitlines()[0].strip()[:max_len] or type(e).__name__
        except Exception:
            return type(e).__name__
 
 
def get_by(strategy: str):
    """Return a Selenium By value from a config strategy name."""
 
    from selenium.webdriver.common.by import By
 
    try:
        return getattr(By, strategy)
    except AttributeError as error:
        raise InvalidLocatorError(f"Unsupported locator strategy: {strategy}", cause=error) from error
 
 
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
 
 
def _is_browser_alive_se(driver, stop_event=None) -> bool:
    if stop_event is not None:
        try:
            if stop_event.is_set():
                return False
        except Exception:
            pass
    if not driver:
        return False
    try:
        _ = driver.current_url
        return True
    except WebDriverException as e:
        # Suppress NewConnectionError spam after Ctrl+C — caller already checks stop_event
        msg = str(e).lower()
        if "newconnectionerror" in msg or "connection refused" in msg or "connectionreseterror" in msg:
            return False
        return False
    except Exception as e:
        msg = str(e).lower()
        if "newconnectionerror" in msg:
            return False
        logger.warning(f"Browser health check unexpected error: {e}", exc_info=False)
        return False
 
 
def open_search_engine(driver, engine: dict, session_logger=None, stop_event=None) -> None:
    """
    Open the selected search engine.
    Raises: BrowserDiedError (expected), EngineConfigError (expected), NavigationError (expected), UnhandledAutomationError (unexpected)
    """
    if stop_event and stop_event.is_set():
        return
    if not _is_browser_alive_se(driver, stop_event):
        raise BrowserDiedError("Browser not alive before opening search engine")
    url = engine.get("url")
    if not url:
        raise EngineConfigError(f"Search engine missing 'url': {engine}")
    try:
        driver.get(url)
    except EngineConfigError:
        raise
    except BrowserDiedError:
        raise
    except WebDriverException as e:
        if session_logger:
            session_logger.warning(f"Failed to open search engine {url}: {e}", extra={'action': 'ENGINE_OPEN', 'status': 'FAILED', 'error_message': str(e)})
        raise NavigationError(f"Navigation failed for {url}: {e}", url=url, cause=e) from e
    except Exception as e:
        if session_logger:
            session_logger.warning(f"Failed to open search engine {url}: {e}", extra={'action': 'ENGINE_OPEN', 'status': 'FAILED', 'error_message': str(e)})
        raise wrap_unexpected(e, f"open_search_engine {url}") from e
 
 
def search_keyword(
    driver,
    engine: dict,
    keyword: str,
    config: dict,
    stop_event=None,
    session_logger=None,
) -> None:
    """
    Search a keyword by typing it into the search box.
 
    The keyword is typed character-by-character instead of
    navigating directly to a generated search URL.
 
    This function is used by the search-engine-first flow.
    """
    if session_logger:
        session_logger.info(f"Performing search for keyword: {keyword}", extra={'action': 'KEYWORD_SEARCH', 'status': 'RUNNING'})
 
    if stop_event and stop_event.is_set():
        return
 
    locator = engine.get("searchBox")
 
    if not locator:
        raise EngineConfigError(
            "Search box configuration not found.", cause=ValueError("missing searchBox")
        )
 
    print(
        f"Typing keyword into search box : {keyword}"
    )
 
    # ---------------------------------------------------------
    # Find search box
    # ---------------------------------------------------------
 
    try:
        search_box = wait_for_element(
            driver,
            locator,
            timeout=15,
        )
    except TimeoutException as e:
        # Expected: search box not rendered (consent, redirect) — fallback to direct URL
        direct_url = build_search_url(engine, keyword)
        if direct_url:
            short = _short_err(e)
            if session_logger:
                session_logger.warning(
                    f"Search box not found; falling back to direct search URL [{short}]",
                    extra={'action': 'KEYWORD_SEARCH', 'status': 'RETRYING', 'error_message': short}
                )
            print(f"Search box not found; navigating directly to {direct_url} [{short}]")
            try:
                driver.get(direct_url)
            except WebDriverException as we:
                raise NavigationError(f"Direct URL fallback failed for {keyword}: {_short_err(we)}", keyword=keyword, cause=we) from we
            random_sleep(
                config["timing"]["sleepMin"],
                config["timing"]["sleepMax"],
                stop_event,
            )
            return
        raise SearchFailedError(f"Search box not found and no direct URL for {keyword}", keyword=keyword, cause=e) from e
    except (InvalidSelectorException, NoSuchElementException) as e:
        raise InvalidLocatorError(f"Invalid searchBox locator {locator}: {_short_err(e)}", cause=e) from e
    except WebDriverException as e:
        # Retryable: browser may be transiently not ready
        raise SearchFailedError(f"Search box wait WebDriverException for {keyword}: {_short_err(e)}", keyword=keyword, cause=e) from e
    except EngineConfigError:
        raise
    except Exception as e:
        raise wrap_unexpected(e, f"search_keyword wait_for_element {keyword}") from e
 
    if stop_event and stop_event.is_set():
        return
 
    # ---------------------------------------------------------
    # Make sure the search box is ready + type + submit
    # Wrap in robust handling - any failure falls back to direct URL
    # ---------------------------------------------------------
    try:
        try:
            search_box.click()
        except Exception:
            pass
 
        if stop_event and stop_event.is_set():
            return
 
        # Clear existing text (fixes fallback keyword duplication like "kw kw anubhav")
        try:
            # Ctrl+A + Delete to clear any existing query (fallback retry case)
            search_box.send_keys(Keys.CONTROL, "a")
            random_sleep(0.2, 0.4, stop_event)
            search_box.send_keys(Keys.DELETE)
            random_sleep(0.2, 0.4, stop_event)
            try:
                search_box.clear()
            except Exception:
                pass
        except Exception:
            pass
 
        if stop_event and stop_event.is_set():
            return
 
        human_typing(
            search_box,
            keyword,
            config["timing"]["typingMin"],
            config["timing"]["typingMax"],
            stop_event,
        )
 
        if stop_event and stop_event.is_set():
            return
 
        print(f"Keyword typed : {keyword}")
 
        press_enter(search_box)
 
        if stop_event and stop_event.is_set():
            return
 
        random_sleep(
            config["timing"]["sleepMin"],
            config["timing"]["sleepMax"],
            stop_event,
        )
 
        print(f"Search submitted : {keyword}")
        return
    except (InvalidSelectorException, NoSuchElementException) as e:
        raise InvalidLocatorError(f"Typing failed due to invalid locator for {keyword}: {_short_err(e)}", keyword=keyword, cause=e) from e
    except TimeoutException as e:
        raise SearchFailedError(f"Typing timeout for {keyword}: {_short_err(e)}", keyword=keyword, cause=e) from e
    except WebDriverException as e:
        # Typing/click/enter failed - fallback to direct URL if possible
        if stop_event and stop_event.is_set():
            raise SearchFailedError(f"Search interrupted for {keyword}", keyword=keyword, cause=e) from e
        direct_url = build_search_url(engine, keyword)
        short = _short_err(e)
        if direct_url and _is_browser_alive_se(driver, stop_event):
            if session_logger:
                session_logger.warning(
                    f"Search typing failed; falling back to direct URL [{short}]",
                    extra={'action': 'KEYWORD_SEARCH', 'status': 'RETRYING', 'error_message': short}
                )
            print(f"Search typing failed; navigating directly to {direct_url} [{short}]")
            try:
                driver.get(direct_url)
                random_sleep(
                    config["timing"]["sleepMin"],
                    config["timing"]["sleepMax"],
                    stop_event,
                )
                return
            except WebDriverException as e2:
                short2 = _short_err(e2)
                if session_logger:
                    session_logger.error(f"Direct URL fallback also failed: {short2}", extra={'action': 'KEYWORD_SEARCH', 'status': 'FAILED', 'error_message': short2})
                raise NavigationError(f"Direct URL fallback failed for {keyword}: {short2}", keyword=keyword, cause=e2) from e2
            except Exception as e2:
                raise wrap_unexpected(e2, f"search_keyword direct fallback {keyword}") from e2
        if session_logger:
            session_logger.error(f"Search failed and no fallback available: {short}", extra={'action': 'KEYWORD_SEARCH', 'status': 'FAILED', 'error_message': short})
        raise SearchFailedError(f"Search failed for {keyword}: {short}", keyword=keyword, cause=e) from e
    except EngineConfigError:
        raise
    except SearchFailedError:
        raise
    except Exception as e:
        if session_logger:
            session_logger.error(f"Search failed unexpectedly for {keyword}: {e}", extra={'action': 'KEYWORD_SEARCH', 'status': 'FAILED', 'error_message': str(e)})
        raise wrap_unexpected(e, f"search_keyword {keyword}") from e
 
 
def is_google_verification_page(driver):
    """
    Detect an actual Google verification / CAPTCHA page.
 
    Avoids scanning the complete HTML source because normal
    Google pages can contain CAPTCHA-related scripts/text.
    """
    return is_captcha_page(driver, engine_name="google")
 
 
def is_captcha_page(driver, engine_name=None, stop_event=None):
    """
    Generic CAPTCHA detection across search engines (Google, Bing, Yahoo, DuckDuckGo).
    Works for any browser (Chrome/Firefox/Edge/Opera/Brave) and future engines.
    Returns True when a CAPTCHA/challenge page is detected.
    """
    if stop_event is not None:
        try:
            if stop_event.is_set():
                return False
        except Exception:
            pass
    try:
        # Avoid driver calls when browser is already dead — prevents NewConnectionError retry spam
        try:
            # Quick alive check without triggering urllib3 retries at WARNING
            _ = driver.current_window_handle  # lighter than current_url but still HTTP; we suppress logs via ERROR level
        except Exception as e:
            msg = str(e).lower()
            if "newconnectionerror" in msg or "connection refused" in msg or "invalid session" in msg or "no such window" in msg:
                return False
            # For other errors, still try current_url path
            pass
        current_url = ""
        page_title = ""
        visible_text = ""
        page_source = ""
        try:
            current_url = (driver.current_url or "").lower()
        except Exception as e:
            msg = str(e).lower()
            if "newconnectionerror" in msg or "connection refused" in msg:
                return False
            current_url = ""
        try:
            page_title = (driver.title or "").lower()
        except Exception as e:
            msg = str(e).lower()
            if "newconnectionerror" in msg or "connection refused" in msg:
                return False
            page_title = ""
        try:
            body_elem = driver.find_element("tag name", "body")
            visible_text = (body_elem.text or "").lower()
        except Exception as e:
            msg = str(e).lower()
            if "newconnectionerror" in msg or "connection refused" in msg:
                return False
            visible_text = ""
        try:
            page_source = (driver.page_source or "").lower()
        except Exception as e:
            msg = str(e).lower()
            if "newconnectionerror" in msg or "connection refused" in msg:
                return False
            page_source = ""
 
        # URL indicators - strong signal
        url_indicators = [
            "/sorry/",
            "captcha",
            "challenge",
            "verify-you-are-human",
            "areyouhuman",
            "/interstitial/",
        ]
        if any(ind in current_url for ind in url_indicators):
            return True
 
        # Text indicators visible to user - covers Bing "One last step" screenshot and others
        text_indicators = [
            "one last step",
            "verify you are human",
            "please solve the challenge",
            "unusual traffic",
            "our systems have detected unusual traffic",
            "our systems have detected unusual traffic from your computer",
            "i'm not a robot",
            "i am not a robot",
            "are you a robot",
            "security check",
            "please complete the security check",
            "suspicious activity",
            "automated requests",
            "we've detected unusual activity",
            "confirm you are human",
            "human verification",
            "are you human",
            "not a robot",
            "verify your humanity",
            "prove you are human",
        ]
        # Check title and visible body text first (avoid false positives from scripts)
        for ind in text_indicators:
            if ind in page_title or ind in visible_text:
                return True
 
        # Generic captcha term in visible text is strong, but avoid script-only false positives
        # Check for captcha checkbox/iframe elements visible
        # Bing: "Verify you are human" checkbox + "One last step" heading
        try:
            # Detect Bing specific combination seen in screenshot
            has_one_last_step = False
            has_verify_human = False
            # Quick text check already done, but element presence confirms
            if "one last step" in visible_text and "verify you are human" in visible_text:
                return True
            # Check for captcha iframe/checkbox elements that may be hidden in DOM
            captcha_selectors = [
                "//*[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'verify you are human')]",
                "//*[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'one last step')]",
                "//input[@type='checkbox' and contains(@aria-label,'human')]",
                "//iframe[contains(@src,'captcha') or contains(@src,'challenge')]",
                "//div[contains(@class,'captcha')]",
            ]
            for xpath in captcha_selectors:
                try:
                    elems = driver.find_elements(By.XPATH, xpath)
                    if elems:
                        # Verify at least one is displayed or text matches
                        for e in elems:
                            try:
                                if e.is_displayed() or e.text:
                                    # Double check text to avoid false positive
                                    txt = (e.text or e.get_attribute("innerText") or "").lower()
                                    if "verify" in txt or "one last step" in txt or e.is_displayed():
                                        return True
                            except Exception:
                                continue
                except Exception:
                    continue
        except Exception:
            pass
 
        # As last resort, check page_source for captcha challenge markers only if visible_text is non-empty to reduce false positives
        if visible_text and "captcha" in page_source and "captcha" in visible_text:
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
    driver, engine: dict, target_domain: str, max_pages: int, stop_event=None, session_logger=None
) -> bool:
    """
    Find the target website in search results. Robust: any page/link error
    is isolated, browser death is detected, and next_page failures don't crash.
    """
    if session_logger:
        try:
            session_logger.info(f"Searching for target website '{target_domain}' in search results.", extra={'action': 'WEBSITE_SEARCH', 'status': 'RUNNING'})
        except Exception:
            pass
 
    from selenium.common.exceptions import StaleElementReferenceException, WebDriverException
 
    # Validate locator
    link_locator = engine.get("resultLinks")
    if not link_locator:
        if session_logger:
            try:
                session_logger.warning(f"Engine missing resultLinks locator", extra={'action': 'WEBSITE_SEARCH', 'status': 'FAILED'})
            except Exception:
                pass
        return False
 
    open_target_mode = engine.get("openTarget", "direct")
    max_pages = max(1, int(max_pages or 1))
    last_page = 0
 
    for page in range(max_pages):
        last_page = page
        if stop_event and stop_event.is_set():
            return False
        if not _is_browser_alive_se(driver, stop_event):
            if stop_event and stop_event.is_set():
                return False
            if session_logger:
                try:
                    session_logger.warning("Browser died during website search", extra={'action': 'WEBSITE_SEARCH', 'status': 'FAILED'})
                except Exception:
                    pass
            return False

        # Get result links - tolerate timeout/no results
        try:
            links = wait_for_elements(driver, link_locator, timeout=10)
        except Exception as e:
            if stop_event and stop_event.is_set():
                return False
            # Suppress NewConnectionError noise on shutdown
            msg = str(e).lower()
            if "newconnectionerror" in msg or "connection refused" in msg:
                return False
            if session_logger:
                try:
                    # Only log at debug for first pages to reduce noise
                    session_logger.info(f"No result links on page {page+1}: {e}", extra={'action': 'WEBSITE_SEARCH', 'status': 'RUNNING'})
                except Exception:
                    pass
            links = []

        for link in links:
            if stop_event and stop_event.is_set():
                return False
            if not _is_browser_alive_se(driver, stop_event):
                return False
            try:
                try:
                    raw_href = link.get_attribute("href")
                except StaleElementReferenceException:
                    continue
                except WebDriverException:
                    continue
                href = extract_result_url(raw_href)
            except StaleElementReferenceException:
                continue
            except Exception:
                continue
 
            if href and is_target_url(href, target_domain):
                print(f"Matched target URL: {href}")
                if session_logger:
                    try:
                        session_logger.info(f"Target matched: {href}", extra={'action': 'WEBSITE_FOUND', 'status': 'SUCCESS', 'url': href})
                    except Exception:
                        pass
                # Open target - best effort with safe handling
                try:
                    if open_target_mode == "direct":
                        driver.get(href)
                    else:
                        try:
                            scroll_and_click(driver, link, stop_event)
                        except StaleElementReferenceException:
                            driver.get(href)
                        except WebDriverException:
                            # Fallback to direct
                            try:
                                driver.get(href)
                            except Exception as e2:
                                if session_logger:
                                    try:
                                        session_logger.warning(f"Failed to open target {href}: {e2}", extra={'action': 'WEBSITE_OPEN', 'status': 'FAILED', 'error_message': str(e2), 'url': href})
                                    except Exception:
                                        pass
                                return False
                        except Exception:
                            driver.get(href)
                except Exception as e:
                    if session_logger:
                        try:
                            session_logger.warning(f"Failed to open matched URL {href}: {e}", extra={'action': 'WEBSITE_OPEN', 'status': 'FAILED', 'error_message': str(e), 'url': href})
                        except Exception:
                            pass
                    # Still consider found even if open fails? We'll return True to let caller decide
                    # But to avoid false success when page didn't load, return True and let visit handle
                    return True
                # Small wait for navigation
                try:
                    time.sleep(1)
                except Exception:
                    pass
                return True
 
        # Try next page if not found
        if stop_event and stop_event.is_set():
            return False
        try:
            has_next = next_page(driver, engine, stop_event)
        except Exception as e:
            if stop_event and stop_event.is_set():
                return False
            msg = str(e).lower()
            if "newconnectionerror" in msg or "connection refused" in msg:
                return False
            if session_logger:
                try:
                    session_logger.info(f"next_page error on page {page+1}: {e}", extra={'action': 'WEBSITE_SEARCH', 'status': 'RUNNING'})
                except Exception:
                    pass
            has_next = False
        if not has_next:
            break
        # Brief pause between pages — interruptible
        try:
            if stop_event:
                if stop_event.wait(1):
                    return False
            else:
                time.sleep(1)
        except Exception:
            pass

    if stop_event and stop_event.is_set():
        return False
    if session_logger:
        try:
            session_logger.warning(f"Target website '{target_domain}' not found after checking {last_page + 1} page(s).", extra={'action': 'WEBSITE_NOT_FOUND', 'status': 'FAILED'})
        except Exception:
            pass
    return False
 
 
def retry_operation_search(driver, engine, target_domain, max_pages, stop_event, session_logger, retries=3, delay=3):
    """
    Retries the find_target_website operation. Isolated: exceptions never crash caller.
    Returns (found, actual_retry_count)
    """
    actual_retry_count = 0
    for attempt in range(1, retries + 1):
        if stop_event and stop_event.is_set():
            return False, actual_retry_count
        if not _is_browser_alive_se(driver, stop_event):
            # Don't spam warning after Ctrl+C
            if stop_event and stop_event.is_set():
                return False, actual_retry_count
            if session_logger:
                try:
                    session_logger.warning("Browser not alive during retry search", extra={'action': 'WEBSITE_SEARCH', 'status': 'FAILED'})
                except Exception:
                    pass
            return False, actual_retry_count

        try:
            found = find_target_website(driver, engine, target_domain, max_pages, stop_event, session_logger)
        except Exception as e:
            found = False
            if stop_event and stop_event.is_set():
                return False, actual_retry_count
            # Suppress NewConnectionError noise on shutdown
            msg = str(e).lower()
            if "newconnectionerror" in msg or "connection refused" in msg:
                return False, actual_retry_count
            if session_logger:
                try:
                    session_logger.warning(f"Find target crashed on attempt {attempt}/{retries}: {e}", extra={'action': 'WEBSITE_SEARCH', 'status': 'FAILED', 'error_message': str(e)})
                except Exception:
                    pass
            else:
                print(f"[SEARCH] find_target_website error: {e}")

        if found:
            return True, actual_retry_count

        if attempt < retries:
            # If shutdown was requested, exit immediately WITHOUT logging retry warning
            if stop_event and stop_event.is_set():
                return False, actual_retry_count
            actual_retry_count += 1
            try:
                if session_logger:
                    # Double-check still not shutting down before spamming console
                    if stop_event and stop_event.is_set():
                        return False, actual_retry_count
                    session_logger.warning(
                        f"Target website not found on attempt {attempt}/{retries}. Retrying in {delay} seconds...",
                        extra={'action': 'WEBSITE_SEARCH_RETRY', 'status': 'RETRYING'}
                    )
                else:
                    if not (stop_event and stop_event.is_set()):
                        print(f"Target not found attempt {attempt}/{retries}, retrying in {delay}s")
            except Exception:
                pass
            if stop_event and stop_event.is_set():
                return False, actual_retry_count
            try:
                if stop_event:
                    # wait returns quickly when event is set, avoiding full delay after Ctrl+C
                    stop_event.wait(delay)
                    if stop_event.is_set():
                        return False, actual_retry_count
                else:
                    time.sleep(delay)
            except Exception:
                pass

    return False, actual_retry_count
 
 