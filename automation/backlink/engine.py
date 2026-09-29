"""
engine.py — Generic config-driven engine for submitting to ping/backlink sites.
Replaces site-specific python functions by dynamically interpreting site configurations.
"""

import logging
import time
from urllib.parse import urlparse

from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By

from automation.backlink import selenium_utils as su
from utils.exceptions import SeoBotError

logger = logging.getLogger(__name__)

class CaptchaSkipped(SeoBotError):
    pass

CAPTCHA_SELECTORS = [
    'iframe[src*="recaptcha/api2/bframe"]',
    'iframe[src*="recaptcha/enterprise/bframe"]',
    'iframe[title*="recaptcha challenge"]',
    'iframe[src*="hcaptcha.com/captcha"]',
    'iframe[title*="hcaptcha challenge"]',
    '#cf-challenge-stage',
    '#challenge-form',
    '#px-captcha',
    'iframe[src*="perimeterx"]',
    'iframe[src*="humansecurity"]',
    'iframe[src*="datadome"]',
    '#datadome-captcha',
    'iframe[src*="arkoselabs"]',
    'iframe[src*="funcaptcha"]',
    '.geetest_panel',
    '.geetest_panel_box',
]

def detect_captcha(driver):
    """Detects on-screen CAPTCHA frames or bot-walls."""
    try:
        title = (driver.title or "").lower()
        if any(x in title for x in ["just a moment", "attention required", "are you human", "access denied", "verify you are human", "pardon our interruption", "request unsuccessful"]):
            return {"found": True, "reason": "page title suggests a bot-check"}
            
        # Execute JS to find visible CAPTCHA elements on screen
        script = """
        for (const sel of arguments[0]) {
            for (const el of document.querySelectorAll(sel)) {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                const onScreen =
                    rect.width > 40 &&
                    rect.height > 40 &&
                    rect.top < window.innerHeight &&
                    rect.bottom > 0 &&
                    rect.left < window.innerWidth &&
                    rect.right > 0;
                if (onScreen && style.display !== 'none' && style.visibility !== 'hidden' && parseFloat(style.opacity || '1') > 0) {
                    return sel;
                }
            }
        }
        return null;
        """
        match = driver.execute_script(script, CAPTCHA_SELECTORS)
        if match:
            return {"found": True, "reason": f'on-screen element matching "{match}"'}
            
        try:
            body_text = driver.find_element(By.TAG_NAME, "body").text.lower()
            if any(x in body_text for x in ["incapsula incident id", "please enable cookies and reload", "unusual traffic from your computer"]):
                return {"found": True, "reason": "page text matches a known bot-wall block message"}
        except Exception:
            pass
            
    except Exception:
        pass
        
    return {"found": False, "reason": None}

def pause_if_captcha(driver, config, stop_event=None, session_logger=None):
    captcha = detect_captcha(driver)
    if not captcha["found"]:
        return

    pause_enabled = config.get("backlink", {}).get("pause_on_captcha", False)
    if not pause_enabled:
        raise CaptchaSkipped(captcha["reason"])

    if session_logger:
        session_logger.warning(f"CAPTCHA detected: {captcha['reason']}. Pausing for human to solve...")
        
    wait_minutes = config.get("backlink", {}).get("captcha_wait_minutes", 3)
    end_time = time.time() + (wait_minutes * 60)
    
    while time.time() < end_time:
        if stop_event and stop_event.is_set():
            raise CaptchaSkipped("Interrupted while waiting for CAPTCHA")
        if not detect_captcha(driver)["found"]:
            if session_logger:
                session_logger.info("CAPTCHA appears solved. Continuing.")
            return
        time.sleep(2)
        
    raise CaptchaSkipped(f"CAPTCHA not solved after {wait_minutes} minutes")


def dismiss_cookie_banners(driver, stop_event=None):
    # Try generic dismiss text pattern via JS
    script = """
    const re = /^(accept( all)?( cookies)?|i agree|agree|allow all|got it|ok|i understand)$/i;
    const candidates = document.querySelectorAll('button, a[role="button"], input[type="button"]');
    for (const el of candidates) {
        const text = (el.textContent || el.value || '').trim();
        if (text.length < 30 && re.test(text)) {
            const rect = el.getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0) {
                el.click();
                return true;
            }
        }
    }
    return false;
    """
    try:
        driver.execute_script(script)
    except Exception:
        pass
    time.sleep(0.5)
    
    # Try specific selectors
    selectors = [
        '#onetrust-accept-btn-handler',
        '.onetrust-close-btn-handler',
        '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll',
        '#CybotCookiebotDialogBodyButtonAccept',
        '.CybotCookiebotDialogBodyButton',
        '#didomi-notice-agree-button',
        '.cc-window .cc-btn.cc-dismiss',
        '.cc-window .cc-btn.cc-allow',
        '.cc-compliance .cc-btn',
        'button[aria-label="Agree"]',
        'button[aria-label="Accept"]',
        'button[aria-label="Accept all"]',
    ]
    for sel in selectors:
        if stop_event and stop_event.is_set(): return
        try:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in els:
                if el.is_displayed():
                    try:
                        el.click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", el)
                    time.sleep(0.3)
        except Exception:
            continue


def _title_for(target) -> str:
    title = (target.get("title") or "").strip()
    if title:
        return title
    keyword = (target.get("keyword") or "").strip()
    if keyword:
        return f"{keyword[:80]}"
    return f"{target.get('url', '')[:80]}"


def _target_values(target) -> dict:
    url = str(target.get("url") or "")
    title = _title_for(target)
    keyword = str(target.get("keyword") or title or url)
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = parsed.netloc or parsed.path.split("/", 1)[0]
    url_no_scheme = url.replace("https://", "", 1).replace("http://", "", 1).rstrip("/")
    return {
        "url": url,
        "title": title,
        "keyword": keyword,
        "host": host,
        "url_no_scheme": url_no_scheme,
        "feed": f"{url.rstrip('/')}/feed",
    }


def _field_value(field, target) -> str:
    values = _target_values(target)
    if "value" in field:
        try:
            return str(field.get("value", "")).format(**values)
        except Exception:
            return str(field.get("value", ""))
    key = field.get("value_from", "url")
    return str(values.get(key, values["url"]))


def generic_submit(driver, site, target, config, stop_event=None, session_logger=None):
    url = target.get("url", "")
    title = _title_for(target)
    
    if session_logger:
        session_logger.info(f"[{site['id']}] Submitting {url}", extra={"action": "BACKLINK_SUBMIT", "status": "RUNNING", "url": url})
        
    driver.get(site["url"])
    time.sleep(1)
    
    # Pre-flight dismissals and checks
    dismiss_cookie_banners(driver, stop_event)
    su.dismiss_popups(driver, stop_event)
    pause_if_captcha(driver, config, stop_event, session_logger)

    input_type = site.get("input_type", "single")
    
    fields = site.get("fields") or []
    if fields:
        for field in fields:
            field_box = su.find_element(
                driver,
                field.get("primary_xpath"),
                field.get("fallbacks"),
                timeout=int(field.get("timeout", 15)),
                stop_event=stop_event,
            )
            su.human_type(field_box, _field_value(field, target), config, stop_event)
    else:
        # Fill Input
        inp_cfg = site.get("input", {})
        if inp_cfg:
            inp = su.find_element(driver, inp_cfg.get("primary_xpath"), inp_cfg.get("fallbacks"), timeout=15, stop_event=stop_event)
            su.human_type(inp, url, config, stop_event)

        # Fill Title (if url_plus_title)
        if input_type == "url_plus_title" and site.get("title"):
            title_cfg = site.get("title", {})
            title_box = su.find_element(driver, title_cfg.get("primary_xpath"), title_cfg.get("fallbacks"), timeout=15, stop_event=stop_event)
            su.human_type(title_box, title, config, stop_event)

    for check_cfg in site.get("checks") or []:
        checkbox = su.find_element(
            driver,
            check_cfg.get("primary_xpath"),
            check_cfg.get("fallbacks"),
            timeout=int(check_cfg.get("timeout", 10)),
            stop_event=stop_event,
        )
        try:
            if not checkbox.is_selected():
                su.safe_click(driver, checkbox, stop_event)
        except Exception:
            su.safe_click(driver, checkbox, stop_event)

    # Submit Steps
    submit_keys = ["submit_step1", "submit_step2", "submit"]
    for step_key in submit_keys:
        if step_key in site:
            step_cfg = site[step_key]
            try:
                btn = su.find_clickable(driver, step_cfg.get("primary_xpath"), step_cfg.get("fallbacks"), timeout=15, stop_event=stop_event)
                su.safe_click(driver, btn, stop_event)
                if session_logger:
                    session_logger.info(f"[{site['id']}] Clicked {step_key}", extra={"action": f"BACKLINK_{step_key.upper()}", "status": "SUCCESS", "url": url})
                time.sleep(2)
                pause_if_captcha(driver, config, stop_event, session_logger)
            except NoSuchElementException as e:
                if session_logger:
                    session_logger.warning(f"[{site['id']}] {step_key} button not found: {e}", extra={"action": f"BACKLINK_{step_key.upper()}", "status": "FAILED", "url": url})
                raise

    if site.get("submit_js"):
        driver.execute_script(site["submit_js"])
        time.sleep(2)
        pause_if_captcha(driver, config, stop_event, session_logger)

    # Mandatory wait to allow AJAX ping requests to complete
    try:
        mandatory_wait = int(site.get("mandatory_wait", 10))
    except (ValueError, TypeError):
        mandatory_wait = 10

    if mandatory_wait > 0:
        if session_logger:
            session_logger.info(f"[{site['id']}] Waiting {mandatory_wait}s for submission to process...", extra={"action": "BACKLINK_WAITING", "status": "RUNNING", "url": url})
        time.sleep(mandatory_wait)

    # Wait for result
    found, text, used = su.wait_for_result(driver, site.get("result"), stop_event, session_logger)
    
    # Generic success heuristic or config-based hint
    success = False
    if found:
        success = True
    elif site.get("success_without_result", False):
        success = True
        text = "Submitted; no configured result element was detected before timeout."
        used = "success_without_result"
        
    return {
        "success": success, 
        "result_text": text, 
        "result_xpath": used, 
        "detail": site.get("result", {}).get("success_hint", "Result check on generic engine")
    }
