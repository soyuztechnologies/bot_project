"""
pingmyurls.py — https://pingmyurls.com
Single URL input + submit. Result table row: url + status <img> ('ping').
"""

from automation.backlink import selenium_utils as su


def submit(driver, site, target, config, stop_event=None, session_logger=None):
    url = target.get("url", "")
    if session_logger:
        session_logger.info(f"[{site['id']}] Submitting {url}", extra={"action": "BACKLINK_SUBMIT", "status": "RUNNING", "url": url})
    driver.get(site["url"])
    su.dismiss_popups(driver, stop_event)

    inp = su.find_element(driver, site["input"]["primary_xpath"], site["input"].get("fallbacks"), timeout=15, stop_event=stop_event)
    su.human_type(inp, url, config, stop_event)

    btn = su.find_clickable(driver, site["submit"]["primary_xpath"], site["submit"].get("fallbacks"), timeout=15, stop_event=stop_event)
    su.safe_click(driver, btn, stop_event)

    found, text, used = su.wait_for_result(driver, site.get("result"), stop_event, session_logger)
    lowered = (text or "").lower()
    success = bool(found) and ("ping" in lowered or url.lower() in lowered or "img." in lowered)
    return {"success": success, "result_text": text, "result_xpath": used, "detail": f"status-img ping check on {site['id']}"}
