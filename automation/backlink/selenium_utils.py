"""
selenium_utils.py

Small robust Selenium helpers for backlink (ping) sites.

All helpers are best-effort + stop_event aware so Ctrl+C
never hangs a session.
"""

import logging
import random
import time

from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

logger = logging.getLogger(__name__)


def is_browser_alive(driver, stop_event=None) -> bool:
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
    except Exception:
        return False


def _candidates(primary_xpath, fallbacks):
    cands = []
    if primary_xpath:
        cands.append(primary_xpath)
    for fb in fallbacks or []:
        if fb and fb not in cands:
            cands.append(fb)
    return cands


def find_element(driver, primary_xpath, fallbacks=None, timeout=12, stop_event=None):
    """Try primary XPath first, then fallbacks. Returns element or raises NoSuchElementException."""
    last_err = None
    for xpath in _candidates(primary_xpath, fallbacks):
        if stop_event is not None and stop_event.is_set():
            raise TimeoutException("interrupted while finding element")
        try:
            el = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
            return el
        except (TimeoutException, NoSuchElementException) as e:
            last_err = e
            continue
        except (StaleElementReferenceException, WebDriverException) as e:
            last_err = e
            continue
    raise NoSuchElementException(
        f"Element not found. Tried: {_candidates(primary_xpath, fallbacks)} last={last_err}"
    )


def find_clickable(driver, primary_xpath, fallbacks=None, timeout=12, stop_event=None):
    last_err = None
    for xpath in _candidates(primary_xpath, fallbacks):
        if stop_event is not None and stop_event.is_set():
            raise TimeoutException("interrupted while finding clickable")
        try:
            el = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            return el
        except (TimeoutException, NoSuchElementException) as e:
            last_err = e
            continue
        except (StaleElementReferenceException, WebDriverException) as e:
            last_err = e
            continue
    raise NoSuchElementException(
        f"Clickable not found. Tried: {_candidates(primary_xpath, fallbacks)} last={last_err}"
    )


def human_type(element, text, config=None, stop_event=None):
    timing = (config or {}).get("timing", {})
    tmin = float(timing.get("typingMin", 0.05))
    tmax = float(timing.get("typingMax", 0.15))
    # Clear first (Ctrl+A + Delete + clear) to avoid stale values
    try:
        element.click()
    except Exception:
        pass
    try:
        element.send_keys(Keys.CONTROL, "a")
        time.sleep(0.2)
        element.send_keys(Keys.DELETE)
    except Exception:
        pass
    try:
        element.clear()
    except Exception:
        pass
    for ch in str(text or ""):
        if stop_event is not None and stop_event.is_set():
            return
        try:
            element.send_keys(ch)
        except StaleElementReferenceException:
            return
        except WebDriverException:
            return
        time.sleep(random.uniform(tmin, tmax))


def scroll_into_view(driver, element):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
        time.sleep(0.6)
    except Exception:
        pass


def safe_click(driver, element, stop_event=None):
    if stop_event is not None and stop_event.is_set():
        return False
    scroll_into_view(driver, element)
    if stop_event is not None and stop_event.is_set():
        return False
    try:
        element.click()
        return True
    except Exception:
        pass
    try:
        driver.execute_script("arguments[0].click();", element)
        return True
    except Exception:
        return False


def dismiss_popups(driver, stop_event=None):
    """Best-effort: close cookie/consent banners that cover ping forms."""
    if not is_browser_alive(driver, stop_event):
        return
    xpaths = [
        "//button[contains(translate(.,'ACCEPT','accept'),'accept')]",
        "//button[contains(translate(.,'AGREE','agree'),'agree')]",
        "//button[contains(translate(.,'GOT IT','got it'),'got it')]",
        "//button[contains(@id,'accept') or contains(@class,'accept')]",
        "//button[@aria-label='Close' or @aria-label='close' or @aria-label='Dismiss']",
        "//div[contains(@id,'cookie')]//button",
    ]
    for xp in xpaths:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            els = driver.find_elements(By.XPATH, xp)
            for el in els[:2]:
                try:
                    if el.is_displayed():
                        try:
                            el.click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", el)
                        time.sleep(0.5)
                except Exception:
                    continue
        except Exception:
            continue


def element_result_text(element) -> str:
    """Extract human-readable result from an element (handles <img> status icons)."""
    if element is None:
        return ""
    try:
        tag = (element.tag_name or "").lower()
    except Exception:
        tag = ""
    parts = []
    try:
        txt = (element.text or "").strip()
        if txt:
            parts.append(txt)
    except Exception:
        pass
    # For <img> status icons the meaning is in alt/title/src
    try:
        if tag == "img":
            for attr in ("alt", "title", "src"):
                try:
                    v = (element.get_attribute(attr) or "").strip()
                except Exception:
                    v = ""
                if v:
                    parts.append(f"{attr}={v}")
        else:
            # A result cell may contain an <img> child
            try:
                imgs = element.find_elements(By.XPATH, ".//img")
                for im in imgs[:3]:
                    for attr in ("alt", "title", "src"):
                        try:
                            v = (im.get_attribute(attr) or "").strip()
                        except Exception:
                            v = ""
                        if v:
                            parts.append(f"img.{attr}={v}")
            except Exception:
                pass
    except Exception:
        pass
    # Outer HTML snippet as last resort (truncated)
    if not parts:
        try:
            html = (element.get_attribute("outerHTML") or "")[:500]
            if html:
                parts.append(html)
        except Exception:
            pass
    return " | ".join(parts).strip()


def wait_for_result(driver, result_cfg, stop_event=None, session_logger=None):
    """Wait until the result element appears. Returns (found: bool, text: str, xpath_used: str)."""
    result_cfg = result_cfg or {}
    primary = result_cfg.get("primary_xpath")
    fallbacks = result_cfg.get("fallbacks") or []
    wait_seconds = int(result_cfg.get("wait_seconds") or 30)
    poll = 1.0
    deadline = time.time() + max(5, wait_seconds)
    last_text = ""
    used = ""
    tried = _candidates(primary, fallbacks)
    while time.time() < deadline:
        if stop_event is not None and stop_event.is_set():
            return False, last_text, used
        if not is_browser_alive(driver, stop_event):
            return False, last_text, used
        for xp in tried:
            try:
                els = driver.find_elements(By.XPATH, xp)
            except Exception:
                continue
            for el in els:
                try:
                    if not el.is_displayed():
                        continue
                except Exception:
                    pass
                txt = element_result_text(el)
                # <br> result pages have no text on the <br> itself -> use parent text
                if not txt and xp.endswith(("br[2]", "br[1]", "/br")):
                    try:
                        parent = el.find_element(By.XPATH, "./..")
                        txt = element_result_text(parent) or (parent.text or "").strip()
                    except Exception:
                        txt = ""
                if txt:
                    last_text = txt
                    used = xp
                    # Non-empty result = site finished rendering for this URL
                    return True, txt, xp
        # Page-level fallback: some sites render result text without our exact xpath.
        # Only used to avoid infinite wait; still reported with used="page-text".
        try:
            body_txt = (driver.find_element(By.TAG_NAME, "body").text or "")
        except Exception:
            body_txt = ""
        low = body_txt.lower()
        if any(k in low for k in ("successfully pinged", "successfully submitted", "has been pinged", "status code", "pinged")):
            last_text = body_txt[:800]
            used = "page-text"
            return True, last_text, used
        if stop_event is not None:
            stop_event.wait(poll)
        else:
            time.sleep(poll)
    if session_logger:
        try:
            session_logger.warning(
                f"Result not visible after {wait_seconds}s (tried {tried})",
                extra={"action": "BACKLINK_RESULT_WAIT", "status": "FAILED"},
            )
        except Exception:
            pass
    return (True, last_text, used) if last_text else (False, "", "")
