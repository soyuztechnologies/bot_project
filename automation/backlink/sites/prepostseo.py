"""
prepostseo.py — https://www.prepostseo.com/ping-multiple-urls-online
Textarea (up to 10 urls) -> pingNow -> startPinging button -> result table.
We submit ONE target url per session (uniform with single-input sites).
"""

import time

from selenium.common.exceptions import NoSuchElementException

from automation.backlink import selenium_utils as su


def submit(driver, site, target, config, stop_event=None, session_logger=None):
    url = target.get("url", "")
    if session_logger:
        session_logger.info(f"[{site['id']}] Submitting {url}", extra={"action": "BACKLINK_SUBMIT", "status": "RUNNING", "url": url})
    driver.get(site["url"])
    su.dismiss_popups(driver, stop_event)

    area = su.find_element(driver, site["input"]["primary_xpath"], site["input"].get("fallbacks"), timeout=18, stop_event=stop_event)
    su.human_type(area, url, config, stop_event)

    # Step 1: pingNow
    s1 = site.get("submit_step1") or {}
    try:
        b1 = su.find_clickable(driver, s1.get("primary_xpath"), s1.get("fallbacks"), timeout=12, stop_event=stop_event)
        su.safe_click(driver, b1, stop_event)
        if session_logger:
            session_logger.info(f"[{site['id']}] Clicked pingNow", extra={"action": "BACKLINK_SUBMIT_STEP1", "status": "SUCCESS", "url": url})
    except NoSuchElementException as e:
        if session_logger:
            session_logger.warning(f"[{site['id']}] pingNow button not found: {e}", extra={"action": "BACKLINK_SUBMIT_STEP1", "status": "FAILED", "url": url})
        raise

    # Small settle so the startPinging control renders
    if stop_event is not None:
        stop_event.wait(2)
    else:
        time.sleep(2)

    # Step 2: startPinging
    s2 = site.get("submit_step2") or {}
    try:
        b2 = su.find_clickable(driver, s2.get("primary_xpath"), s2.get("fallbacks"), timeout=15, stop_event=stop_event)
        su.safe_click(driver, b2, stop_event)
        if session_logger:
            session_logger.info(f"[{site['id']}] Clicked startPinging", extra={"action": "BACKLINK_SUBMIT_STEP2", "status": "SUCCESS", "url": url})
    except NoSuchElementException as e:
        if session_logger:
            session_logger.warning(f"[{site['id']}] startPinging button not found: {e}", extra={"action": "BACKLINK_SUBMIT_STEP2", "status": "FAILED", "url": url})
        raise

    found, text, used = su.wait_for_result(driver, site.get("result"), stop_event, session_logger)
    # Any non-empty status cell for our webpage row = site finished pinging
    success = bool(found and text)
    return {"success": success, "result_text": text, "result_xpath": used, "detail": f"webpage/status table check on {site['id']}"}
