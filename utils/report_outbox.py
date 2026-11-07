"""
The report email of every run, kept on disk until it has really been sent.

A run writes its report to logs/report_outbox/<job_id>.json when it starts and keeps it
up to date. When the run ends it sends the email itself and removes the file. If the
file is still there after the run's process is gone, the email did not go out (the bot
was force-killed, its window was closed, the PC lost its network, Gmail refused it), so
the dashboard or the next bot of this install sends it. A report can in the worst case
arrive twice, if a bot dies between sending it and removing the file; it is never
silently dropped.

Delivery has one of these end states, kept in <job_id>.done or <job_id>.failed:
    sent, disabled (email.enabled=false), or the reason it could not be sent.
"""

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .run_control import run_is_alive

logger = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).resolve().parents[1]
OUTBOX_DIR = PROJECT_DIR / "logs" / "report_outbox"

INLINE_RETRY_PAUSES = (5, 15)  # seconds between the attempts the ending bot makes itself
MAX_RETRY_WAIT = 15 * 60
GIVE_UP_AFTER = 7 * 24 * 3600
CLAIM_STALE_AFTER = 10 * 60
MARKER_KEEP = 24 * 3600


def _path(job_id, suffix=".json"):
    return OUTBOX_DIR / f"{job_id}{suffix}"


def save(record):
    """Atomic, so a kill during this write can't lose the previous version."""
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    tmp = OUTBOX_DIR / f"{record['job_id']}.{uuid.uuid4().hex[:8]}.tmp"
    tmp.write_text(json.dumps(record, default=str), "utf-8")
    tmp.replace(_path(record["job_id"]))


def _finish(job_id, suffix, text):
    """The marker goes first and is what counts: on Windows the report can't be deleted while
    another process is reading it, and it must not be sent again if it stays behind."""
    try:
        OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
        _path(job_id, suffix).write_text(text, "utf-8")
    except OSError:
        pass
    _remove_report(job_id)


def _remove_report(job_id):
    try:
        _path(job_id).unlink(missing_ok=True)
    except OSError:
        pass


def _already_finished(job_id):
    return _path(job_id, ".done").exists() or _path(job_id, ".failed").exists()


def report_state(job_id):
    """('sent' | 'disabled' | 'pending' | 'failed' | 'unknown', reason)"""
    try:
        done = _path(job_id, ".done")
        if done.exists():
            return done.read_text("utf-8").strip(), ""
        failed = _path(job_id, ".failed")
        if failed.exists():
            return "failed", failed.read_text("utf-8").strip()
        pending = _path(job_id)
        if pending.exists():
            return "pending", str(json.loads(pending.read_text("utf-8")).get("last_error") or "")
    except (OSError, ValueError):
        pass
    return "unknown", ""


def _load_config():
    try:
        return json.loads((PROJECT_DIR / "config.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def send(record, attempts=1):
    """Try to send one report. Returns the outcome; the record stays on disk unless it is final."""
    from .mailer import send_report_email

    job_id = record.get("job_id")
    html_path, json_path = record.get("html_path"), record.get("json_path")
    outcome = "failed: nothing attempted"
    for attempt in range(max(1, attempts)):
        if attempt:
            time.sleep(INLINE_RETRY_PAUSES[min(attempt - 1, len(INLINE_RETRY_PAUSES) - 1)])
        try:
            outcome = send_report_email(_load_config(), record["summary"], record["results"], html_path, json_path)
        except Exception as exc:  # e.g. a bad value in the report must not lose the email
            logger.error(f"Report email could not be built: {exc}", exc_info=True)
            outcome = f"failed: {exc}"
        if outcome in ("sent", "disabled", "no_password"):
            break

    if not job_id:
        return outcome
    if outcome in ("sent", "disabled"):
        _finish(job_id, ".done", outcome)
    elif outcome == "no_password":
        # Waiting won't help, and setting the password later shouldn't release a pile of old reports.
        logger.error(f"Report email of {job_id} NOT sent: GMAIL_APP_PASSWORD is not set in .env.")
        _finish(job_id, ".failed", "GMAIL_APP_PASSWORD is not set in .env")
    else:
        record["attempts"] = int(record.get("attempts") or 0) + 1
        record["last_error"] = outcome.replace("failed: ", "", 1)
        record["next_try"] = time.time() + min(MAX_RETRY_WAIT, 60 * 2 ** (record["attempts"] - 1))
        logger.error(f"Report email of {job_id} NOT sent yet, will retry: {record['last_error']}")
        try:
            save(record)
        except OSError as exc:
            logger.error(f"Could not keep the report of {job_id} for retrying: {exc}")
    return outcome


def _complete_abandoned(record):
    """The bot died before finishing its report: finish it from the last state it saved."""
    if record.get("finalized"):
        return
    summary, results = record["summary"], record["results"]
    planned = record.get("total_jobs") or 0
    note = "The bot was force-stopped or its window was closed before it could finish."
    if planned:
        note += f" This report covers the {len(results)} of {planned} planned jobs recorded by then."
    if not results:
        results.append({
            "browser": "unknown", "target": (summary.get("targetUrls") or [""])[0], "keyword": "Startup/Initialization",
            "status": "interrupted", "message": note, "captcha_encountered": "False", "engine": "system",
            "assignedEngine": "system", "url": "",
        })
        summary["byStatus"] = {"interrupted": 1}
        summary["byBrowser"] = {"unknown": {"total": 1, "interrupted": 1}}
        summary["totalAttempts"] = 1
    summary["status"] = "INTERRUPTED"
    summary["errorMessage"] = note
    summary["finishedAt"] = record.get("saved_at") or summary.get("finishedAt")

    try:
        from .report import RunLogger

        started = datetime.strptime(summary["startedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        report = RunLogger(target_urls=summary.get("targetUrls"), started_at=started,
                           automation_type=summary.get("automationType", "Unknown"),
                           user_name=summary.get("userName"), user_email=summary.get("userEmail"))
        report.results = results
        if record.get("json_path"):
            report.json_path, report.html_path = Path(record["json_path"]), Path(record["html_path"])
        record["json_path"], record["html_path"] = report.write_json(), report.write_html()
    except Exception as exc:
        logger.warning(f"Could not rewrite the report files of {record.get('job_id')}: {exc}")
    try:
        from .local_tracker import mark_local_run_interrupted

        mark_local_run_interrupted(record.get("run_id"))
    except Exception as exc:
        logger.warning(f"Could not update the run history for {record.get('job_id')}: {exc}")
    try:
        from .database import close_job_rows

        close_job_rows(record.get("job_id"))
    except Exception as exc:
        logger.warning(f"Could not close the rows of {record.get('job_id')}: {exc}")
    record["finalized"] = True


def _tidy():
    now = time.time()
    for path in OUTBOX_DIR.glob("*"):
        try:
            age = now - path.stat().st_mtime
            if (path.suffix == ".claim" and age > CLAIM_STALE_AFTER) or (path.suffix in (".done", ".tmp") and age > MARKER_KEEP):
                path.unlink()  # a stale claim: its sender died while sending
        except OSError:
            pass


def _claim(job_id):
    """Only one process can create this file. (Renaming the report instead is not enough:
    on Windows several processes can each succeed in renaming the same file.)"""
    try:
        os.close(os.open(_path(job_id, ".claim"), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        return True
    except OSError:
        return False


def _is_due(record, job_id, owner_gone):
    this_job = record["job_id"]
    if not (owner_gone and this_job == job_id):
        owner = record.get("owner") or {}
        try:
            if owner and run_is_alive(owner):
                return False
        except Exception:
            return False
    return time.time() >= float(record.get("next_try") or 0)


def deliver_pending(job_id=None, attempts=1, owner_gone=False):
    """Send the reports whose run is over but which are still here. Safe to call from
    several processes at once. owner_gone: the caller knows this job's process has ended."""
    if not OUTBOX_DIR.exists():
        return
    _tidy()
    for path in list(OUTBOX_DIR.glob("*.json")):
        this_job = path.stem
        if job_id and this_job != job_id:
            continue
        if _already_finished(this_job):
            _remove_report(this_job)
            continue
        try:
            record = json.loads(path.read_text("utf-8"))
        except OSError:
            continue
        except ValueError:
            logger.error(f"Unreadable report in the outbox, keeping it aside: {path.name}")
            try:
                path.replace(path.with_suffix(".bad"))
            except OSError:
                pass
            continue
        record["job_id"] = this_job
        if not _is_due(record, job_id, owner_gone) or not _claim(this_job):
            continue
        try:
            # Check again now that it is ours: the previous holder may have just dealt with it.
            if _already_finished(this_job):
                continue
            try:
                record = json.loads(path.read_text("utf-8"))
            except (OSError, ValueError):
                continue
            record["job_id"] = this_job
            if not _is_due(record, job_id, owner_gone):
                continue
            if time.time() - float(record.get("created_at") or time.time()) > GIVE_UP_AFTER:
                logger.error(f"Giving up on the report of {this_job}: {record.get('last_error')}")
                _finish(this_job, ".failed", str(record.get("last_error") or "not sent within 7 days"))
                continue
            _complete_abandoned(record)
            send(record, attempts=attempts)
        except Exception as exc:
            logger.error(f"Report of {this_job} could not be processed: {exc}", exc_info=True)
        finally:
            try:
                _path(this_job, ".claim").unlink(missing_ok=True)
            except OSError:
                pass
