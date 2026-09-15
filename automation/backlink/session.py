"""
session.py — Generate Backlinks parallel runner.

Requirement mapping:
  "read all these websites one by one"  -> outer loop over ping sites (sequential)
  "open 5 sessions in parallel"          -> `sessions.parallel` browsers per batch (default 5)
  "put first 5, next 5, next 5 ... in batches" -> targets chunked by parallel
  "submit different links"               -> each browser in a batch gets a DIFFERENT target url
  "wait until website finish"            -> per-site explicit result wait (see sites/*)
  "write logs to DB"                     -> automation_runs + automation_logs (automation_type BACKLINK)
  "close sessions and continue next"     -> browser closed per job; next batch starts after join
"""

import logging
import queue
import threading
import time
import uuid
from datetime import datetime, timezone

from automation.backlink.handlers import get_handler
from automation.backlink.selenium_utils import is_browser_alive
from browser.browser import close_browser, setup_browser
from browser.browser_selector import select_browser
from utils.database import create_automation_run, save_backlink_submission, update_automation_run
from utils.exceptions import (
    BrowserError,
    SeoBotError,
    UnhandledAutomationError,
    wrap_unexpected,
)
from utils.helpers import build_browser_mode

logger = logging.getLogger(__name__)

_ACTIVE_DRIVERS = set()
_ACTIVE_DRIVERS_LOCK = threading.Lock()
_CLOSED_DRIVER_IDS = set()
_CLOSED_DRIVER_IDS_LOCK = threading.Lock()
_STATS_LOCK = threading.Lock()


class SessionLoggerAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        kwargs["extra"] = {**(self.extra or {}), **(kwargs.get("extra") or {})}
        return msg, kwargs


def _register_driver(driver):
    with _ACTIVE_DRIVERS_LOCK:
        _ACTIVE_DRIVERS.add(driver)


def _unregister_driver(driver):
    with _ACTIVE_DRIVERS_LOCK:
        _ACTIVE_DRIVERS.discard(driver)


def close_active_drivers(stop_event=None):
    try:
        from utils.logger import silence_noisy_loggers

        silence_noisy_loggers()
    except Exception:
        pass
    with _ACTIVE_DRIVERS_LOCK:
        drivers = list(_ACTIVE_DRIVERS)
    for driver in drivers:
        try:
            ok = close_browser(driver, timeout=4.0)
            with _ACTIVE_DRIVERS_LOCK:
                _ACTIVE_DRIVERS.discard(driver)
            with _CLOSED_DRIVER_IDS_LOCK:
                if ok:
                    _CLOSED_DRIVER_IDS.add(id(driver))
        except Exception:
            pass


def _safe_create_run(*args, **kwargs):
    try:
        create_automation_run(*args, **kwargs)
    except Exception as e:
        logger.warning(f"DB create_automation_run failed (non-fatal): {e}", exc_info=False)


def _safe_update_run(*args, **kwargs):
    try:
        update_automation_run(*args, **kwargs)
    except Exception as e:
        logger.warning(f"DB update_automation_run failed (non-fatal): {e}", exc_info=False)


def _safe_save_backlink(doc):
    """Persist one flat backlink document. Never raises."""
    try:
        save_backlink_submission(doc)
    except Exception as e:
        logger.warning(f"DB save_backlink_submission failed (non-fatal): {e}", exc_info=False)


def chunked(items, size):
    size = max(1, int(size or 1))
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _record(stats, bucket, keyword, engine):
    with _STATS_LOCK:
        lst = stats.get(bucket, [])
        if not any(d.get("keyword") == keyword and d.get("engine") == engine for d in lst):
            lst.append({"keyword": keyword, "engine": engine})


def run_backlink_job(site, target, config, stop_event, stats):
    """One browser session: submit ONE target url to ONE ping site."""
    driver = None
    run_id = uuid.uuid4()
    site_id = site.get("id", "unknown")
    target_url = target.get("url", "")
    keyword = target.get("keyword") or target_url
    selected_browser = "chrome"
    status = None
    session_logger = None
    try:
        selected_browser = str(select_browser(config)).lower()
    except Exception:
        selected_browser = "chrome"
    browser_mode = build_browser_mode(config, selected_browser)
    job_started_at = datetime.now(timezone.utc)

    def _save_backlink(status, result_text="", result_xpath="", detail=""):
        """Write the flat per-submission document to the `backlinks` collection."""
        try:
            finished_at = datetime.now(timezone.utc)
            _safe_save_backlink(
                {
                    "run_id": str(run_id),
                    "site_id": site_id,
                    "site_url": site.get("url", ""),
                    "target_url": target_url,
                    "target_title": target.get("title", ""),
                    "keyword": keyword,
                    "category": target.get("category", ""),
                    "status": status,
                    "result_text": str(result_text or "")[:2000],
                    "result_xpath": str(result_xpath or ""),
                    "detail": str(detail or ""),
                    "browser_mode": build_browser_mode(config, selected_browser),
                    "started_at": job_started_at,
                    "finished_at": finished_at,
                    "duration_seconds": round((finished_at - job_started_at).total_seconds(), 1),
                }
            )
        except Exception:
            pass

    session_logger = SessionLoggerAdapter(
        logger,
        {
            "keyword": target_url,
            "engine": site_id,
            "search_keyword": keyword,
            "session_id": run_id,
            "app_module": "BACKLINK",
            "website": config.get("website", {}).get("domain", "anubhavtrainings.com"),
            "target": target_url,
            "thread_id": threading.get_ident(),
        },
    )
    _safe_create_run(run_id, "BACKLINK", target_url, keyword, browser_mode, target_url, search_engine=site_id)

    if stop_event.is_set():
        status = "INTERRUPTED"
        _record(stats, "interrupted", target_url, site_id)
        _safe_update_run(run_id, datetime.now(timezone.utc), status, 0, 0, 0)
        _save_backlink(status, detail="interrupted before browser startup")
        return

    session_logger.info(f"Starting backlink session: {target_url} -> {site_id}", extra={"action": "BACKLINK_STARTED", "status": "RUNNING", "url": target_url})

    # --- browser startup (with chrome fallback) ---
    try:
        driver = setup_browser(config, selected_browser)
        _register_driver(driver)
        session_logger.info(f"Browser started: {selected_browser}", extra={"action": "BROWSER_STARTED", "status": "SUCCESS"})
    except Exception as e:
        if selected_browser != "chrome":
            try:
                session_logger.warning(f"Browser '{selected_browser}' failed ({e}), fallback to chrome", extra={"action": "BROWSER_FALLBACK", "status": "RETRYING", "error_message": str(e)})
                driver = setup_browser(config, "chrome")
                _register_driver(driver)
                selected_browser = "chrome"
            except Exception as fb_e:
                session_logger.error(f"Browser startup failed: {e} | fallback failed: {fb_e}", exc_info=True, extra={"action": "BROWSER_START_FAILED", "status": "FAILED", "error_message": str(fb_e)})
                _record(stats, "failed", target_url, site_id)
                _safe_update_run(run_id, datetime.now(timezone.utc), "FAILED", 0, 1, 0)
                _save_backlink("FAILED", detail=f"browser startup failed: {e} | fallback failed: {fb_e}")
                return
        else:
            session_logger.error(f"Browser startup failed: {e}", exc_info=True, extra={"action": "BROWSER_START_FAILED", "status": "FAILED", "error_message": str(e)})
            _record(stats, "failed", target_url, site_id)
            _safe_update_run(run_id, datetime.now(timezone.utc), "FAILED", 0, 1, 0)
            _save_backlink("FAILED", detail=f"browser startup failed: {e}")
            return

    if stop_event.is_set():
        status = "INTERRUPTED"
        _record(stats, "interrupted", target_url, site_id)
        _safe_update_run(run_id, datetime.now(timezone.utc), status, 0, 0, 0)
        _save_backlink(status, detail="interrupted after browser startup")
        if driver is not None:
            try:
                close_browser(driver, timeout=4.0)
            except Exception:
                pass
            _unregister_driver(driver)
        return
    if not is_browser_alive(driver, stop_event):
        session_logger.warning("Browser died immediately after startup", extra={"action": "BROWSER_HEALTH", "status": "FAILED"})
        _record(stats, "failed", target_url, site_id)
        _safe_update_run(run_id, datetime.now(timezone.utc), "FAILED", 0, 1, 0)
        _save_backlink("FAILED", detail="browser died immediately after startup")
        if driver is not None:
            try:
                close_browser(driver, timeout=4.0)
            except Exception:
                pass
            _unregister_driver(driver)
        return

    # --- submit (browser always closed in finally) ---
    try:
        try:
            handler = get_handler(site_id)
        except Exception as e:
            session_logger.error(f"No handler for site '{site_id}': {e}", extra={"action": "BACKLINK_SUBMIT", "status": "FAILED", "error_message": str(e), "url": target_url})
            _record(stats, "failed", target_url, site_id)
            _safe_update_run(run_id, datetime.now(timezone.utc), "FAILED", 0, 1, 0)
            _save_backlink("FAILED", detail=f"no handler for site '{site_id}': {e}")
            return

        try:
            result = handler(driver, site, target, config, stop_event, session_logger)
        except Exception as e:
            if stop_event.is_set():
                status = "INTERRUPTED"
                _record(stats, "interrupted", target_url, site_id)
                _safe_update_run(run_id, datetime.now(timezone.utc), status, 0, 0, 0)
                _save_backlink(status, detail=f"interrupted during submit: {e}")
                return
            wrapped = e if isinstance(e, SeoBotError) else wrap_unexpected(e, f"backlink {site_id} {target_url}")
            session_logger.error(f"Backlink submit failed ({site_id} | {target_url}): {wrapped}", exc_info=True, extra={"action": "BACKLINK_SUBMITTED", "status": "FAILED", "error_message": str(wrapped), "url": target_url})
            _record(stats, "failed", target_url, site_id)
            _safe_update_run(run_id, datetime.now(timezone.utc), "FAILED", 0, 1, 0)
            _save_backlink("FAILED", result_text=str(wrapped)[:2000], detail="submit handler raised")
            return

        if stop_event.is_set():
            _record(stats, "interrupted", target_url, site_id)
            _safe_update_run(run_id, datetime.now(timezone.utc), "INTERRUPTED", 0, 0, 0)
            _save_backlink("INTERRUPTED", detail="interrupted after submit, before result handling")
            return

        ok = bool((result or {}).get("success"))
        result_text = str((result or {}).get("result_text") or "")[:2000]
        result_xpath = str((result or {}).get("result_xpath") or "")
        if ok:
            session_logger.info(
                f"Backlink submitted OK ({site_id} | {target_url}) :: {result_text[:300]}",
                extra={"action": "BACKLINK_SUBMITTED", "status": "SUCCESS", "url": target_url, "error_message": None},
            )
            _record(stats, "success", target_url, site_id)
            _safe_update_run(run_id, datetime.now(timezone.utc), "SUCCESS", 1, 0, 0)
            _save_backlink("SUCCESS", result_text=result_text, result_xpath=result_xpath, detail=(result or {}).get("detail", ""))
        else:
            session_logger.warning(
                f"Backlink submit finished without success signal ({site_id} | {target_url}) :: {result_text[:300]} xpath={result_xpath}",
                extra={"action": "BACKLINK_SUBMITTED", "status": "FAILED", "url": target_url, "error_message": result_text[:500]},
            )
            _record(stats, "failed", target_url, site_id)
            _safe_update_run(run_id, datetime.now(timezone.utc), "FAILED", 0, 1, 0)
            _save_backlink("FAILED", result_text=result_text, result_xpath=result_xpath, detail=(result or {}).get("detail", ""))
    finally:
        if driver is not None:
            try:
                closed = close_browser(driver, timeout=4.0)
                _unregister_driver(driver)
                with _CLOSED_DRIVER_IDS_LOCK:
                    if closed:
                        _CLOSED_DRIVER_IDS.add(id(driver))
            except Exception as e:
                try:
                    session_logger.warning(f"Browser close failed: {e}", extra={"action": "BROWSER_CLOSE", "status": "FAILED", "error_message": str(e)})
                except Exception:
                    pass
                _unregister_driver(driver)


def _batch_worker(job_q, config, stop_event, stats):
    while not stop_event.is_set():
        try:
            job = job_q.get_nowait()
        except queue.Empty:
            return
        site, target = job
        try:
            run_backlink_job(site, target, config, stop_event, stats)
        except Exception as e:
            logger.error(f"Backlink worker error ({site.get('id')} | {target.get('url')}): {e}", exc_info=True)
            _record(stats, "failed", target.get("url", ""), site.get("id", ""))
        finally:
            try:
                job_q.task_done()
            except Exception:
                pass


def start_parallel_backlink_sessions(sites, targets, config):
    """Outer: sites one-by-one. Inner: targets in batches of `parallel` parallel browsers."""
    stats = {"total": 0, "success": [], "failed": [], "interrupted": []}
    sites = [s for s in (sites or []) if s.get("enabled", True)]
    targets = list(targets or [])
    if not sites:
        logger.warning("No backlink sites enabled")
        return stats
    if not targets:
        logger.warning("No backlink targets to submit")
        return stats

    try:
        parallel = int(config.get("sessions", {}).get("parallel", 5))
    except Exception:
        parallel = 5
    parallel = max(1, parallel)

    total_jobs = len(sites) * len(targets)
    stats["total"] = total_jobs
    stop_event = threading.Event()
    logger.info(
        f"Backlink run: {len(sites)} site(s) x {len(targets)} target(s) = {total_jobs} jobs | {parallel} parallel/batch",
        extra={"action": "BACKLINK_RUN_START", "status": "RUNNING"},
    )

    interrupted = False
    try:
        for site in sites:
            if stop_event.is_set():
                break
            site_id = site.get("id")
            logger.info(f"Backlink site start: {site_id} ({site.get('url')}) — {len(targets)} targets in batches of {parallel}")
            for batch_no, batch in enumerate(chunked(targets, parallel), start=1):
                if stop_event.is_set():
                    break
                logger.info(f"[{site_id}] Batch {batch_no}: {len(batch)} session(s) in parallel :: {[t.get('url') for t in batch]}")
                job_q = queue.Queue()
                for t in batch:
                    job_q.put((site, t))
                workers = []
                for i in range(min(parallel, len(batch))):
                    w = threading.Thread(target=_batch_worker, args=(job_q, config, stop_event, stats), daemon=True, name=f"Backlink-{site_id}-B{batch_no}-W{i+1}")
                    workers.append(w)
                for w in workers:
                    w.start()
                # Wait for this batch to finish before opening the next batch
                while job_q.unfinished_tasks > 0:
                    if stop_event.is_set():
                        break
                    time.sleep(0.5)
                for w in workers:
                    w.join(timeout=5)
                # Ensure browsers of this batch are really closed before next batch
                try:
                    close_active_drivers(stop_event)
                except Exception:
                    pass
                logger.info(f"[{site_id}] Batch {batch_no} done (sessions closed) — continuing to next batch")
            logger.info(f"Backlink site done: {site_id}")
    except KeyboardInterrupt:
        interrupted = True
        try:
            from utils.logger import silence_noisy_loggers

            silence_noisy_loggers()
        except Exception:
            pass
        logger.info("Ctrl+C — stopping backlink sessions...", extra={"action": "BACKLINK_INTERRUPT", "status": "RUNNING"})
        stop_event.set()
        try:
            close_active_drivers(stop_event)
        except Exception:
            pass
    finally:
        if stop_event.is_set() or interrupted:
            # Mark anything not yet accounted as interrupted
            try:
                accounted = {(d.get("keyword"), d.get("engine")) for d in stats["success"] + stats["failed"] + stats["interrupted"]}
                for site in sites:
                    for t in targets:
                        key = (t.get("url"), site.get("id"))
                        if key not in accounted:
                            stats["interrupted"].append({"keyword": key[0], "engine": key[1]})
            except Exception:
                pass
        try:
            close_active_drivers(stop_event)
        except Exception:
            pass
        logger.info(
            f"Backlink run finished: total={stats['total']} success={len(stats['success'])} failed={len(stats['failed'])} interrupted={len(stats['interrupted'])}",
            extra={"action": "BACKLINK_RUN_FINISHED", "status": "SUCCESS"},
        )
    return stats
