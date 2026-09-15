"""
free_backlinks.py — https://free-backlinks.net/ping-my-url.html
URL input + Title input. Result text contains status code (400/0/500/200).
"""

from automation.backlink import selenium_utils as su


def _title_for(target) -> str:
    title = (target.get("title") or "").strip()
    if title:
        return title
    keyword = (target.get("keyword") or "").strip()
    if keyword:
        return f"Anubhav Trainings - {keyword[:80]}"
    return f"Anubhav Trainings - {target.get('url', '')[:80]}"


def submit(driver, site, target, config, stop_event=None, session_logger=None):
    url = target.get("url", "")
    title = _title_for(target)
    if session_logger:
        session_logger.info(f"[{site['id']}] Submitting {url} | title={title}", extra={"action": "BACKLINK_SUBMIT", "status": "RUNNING", "url": url})
    driver.get(site["url"])
    su.dismiss_popups(driver, stop_event)

    url_box = su.find_element(driver, site["input"]["primary_xpath"], site["input"].get("fallbacks"), timeout=15, stop_event=stop_event)
    su.human_type(url_box, url, config, stop_event)

    title_cfg = site.get("title") or {}
    title_box = su.find_element(driver, title_cfg.get("primary_xpath"), title_cfg.get("fallbacks"), timeout=15, stop_event=stop_event)
    su.human_type(title_box, title, config, stop_event)

    btn = su.find_clickable(driver, site["submit"]["primary_xpath"], site["submit"].get("fallbacks"), timeout=15, stop_event=stop_event)
    su.safe_click(driver, btn, stop_event)

    found, text, used = su.wait_for_result(driver, site.get("result"), stop_event, session_logger)
    # Site echoes a status code/result text when it finishes; capture it verbatim.
    success = bool(found and text)
    return {"success": success, "result_text": text, "result_xpath": used, "detail": f"status-code text check on {site['id']} (title={title})"}
