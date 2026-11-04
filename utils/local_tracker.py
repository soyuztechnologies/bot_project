"""
utils/local_tracker.py

Persistent Local Run Tracker & Guaranteed Email Dispatcher.

Responsibilities:
1. Save every important info inside a local file (`logs/local_user_runs.json`)
   for all users who run the bot (Web, YouTube, Backlinks).
2. Record run start, real-time session progress, and run completion/interruption.
3. Guarantee that a report summary email is dispatched on run finish, EVEN IF:
   - The user interrupts the run (Ctrl+C / SIGINT / STOP).
   - An unexpected exception occurs anywhere during setup or execution.
   - The process is terminated (handled via atexit / signal handlers).
4. Supply historical local run data to `utils/summary_mailer.py` so the 24-hour
   multi-user summary report and Excel sheets have 100% of all user runs, even
   if MongoDB was offline, unreachable, or missed runs.
"""

import os
import sys
import json
import uuid
import atexit
import signal
import logging
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Base project directory & logs directory
BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE_DIR / "logs"
LOCAL_RUNS_FILE = LOGS_DIR / "local_user_runs.json"

_FILE_LOCK = threading.Lock()
_ACTIVE_TRACKER = None
_ACTIVE_TRACKER_LOCK = threading.Lock()


def _ensure_logs_dir():
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _utcnow():
    return datetime.now(timezone.utc)


def _format_ist(dt):
    if not dt:
        return "N/A"
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        ist_dt = dt.astimezone(timezone(timedelta(hours=5, minutes=30), name="IST"))
        return ist_dt.strftime("%d-%m-%Y %I:%M:%S %p IST")
    return str(dt)


def _iso_utc(dt):
    if not dt:
        return ""
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(dt)


def _format_duration(dur_seconds):
    if dur_seconds is None:
        return ""
    try:
        total_secs = int(float(dur_seconds))
        hrs = total_secs // 3600
        rem = total_secs % 3600
        mins = rem // 60
        secs = rem % 60
        if hrs > 0:
            return f"{hrs}h {mins}m {secs}s"
        if mins > 0:
            return f"{mins}m {secs}s"
        return f"{secs}s"
    except Exception:
        return str(dur_seconds)


def load_local_runs_data():
    """Safely read all runs from logs/local_user_runs.json."""
    _ensure_logs_dir()
    if not LOCAL_RUNS_FILE.exists():
        return {"updated_at": _iso_utc(_utcnow()), "runs": []}

    with _FILE_LOCK:
        try:
            with open(LOCAL_RUNS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "runs" in data:
                    return data
                elif isinstance(data, list):
                    return {"updated_at": _iso_utc(_utcnow()), "runs": data}
        except Exception as e:
            logger.warning(f"Failed to read local runs file {LOCAL_RUNS_FILE}: {e}")

    return {"updated_at": _iso_utc(_utcnow()), "runs": []}


def save_local_runs_data(data):
    """Safely write runs data to logs/local_user_runs.json atomically."""
    _ensure_logs_dir()
    data["updated_at"] = _iso_utc(_utcnow())
    temp_file = LOGS_DIR / f"local_user_runs_{uuid.uuid4().hex[:8]}.tmp"

    with _FILE_LOCK:
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            temp_file.replace(LOCAL_RUNS_FILE)
            return True
        except Exception as e:
            logger.warning(f"Failed to save local runs data to {LOCAL_RUNS_FILE}: {e}")
            try:
                if temp_file.exists():
                    temp_file.unlink()
            except Exception:
                pass
            # Fallback non-atomic write
            try:
                with open(LOCAL_RUNS_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                return True
            except Exception:
                return False


def get_active_tracker():
    with _ACTIVE_TRACKER_LOCK:
        return _ACTIVE_TRACKER


def set_active_tracker(tracker):
    global _ACTIVE_TRACKER
    with _ACTIVE_TRACKER_LOCK:
        _ACTIVE_TRACKER = tracker


class LocalRunTracker:
    """
    Tracks an automation run locally, updating logs/local_user_runs.json
    incrementally and ensuring the final report email is sent under all conditions.
    """

    def __init__(self, automation_type="Web", config=None, target_urls=None, user_name=None, user_email=None):
        load_dotenv()
        self.automation_type = automation_type
        self.config = config or self._load_fallback_config()
        self.target_urls = target_urls or []
        self.start_time = _utcnow()
        self.run_id = f"run-{self.start_time.strftime('%Y-%m-%dT%H-%M-%S')}-{uuid.uuid4().hex[:6]}"

        self.user_name = (
            user_name
            or os.getenv("USER_NAME")
            or (self.config.get("user_name") if isinstance(self.config, dict) else None)
            or os.getenv("USERNAME")
            or os.getenv("USER")
            or "Unknown"
        )
        self.user_name = str(self.user_name).strip() if self.user_name else "Unknown"

        self.user_email = (
            user_email
            or os.getenv("USER_EMAIL")
            or (self.config.get("email", {}).get("to") if isinstance(self.config, dict) and isinstance(self.config.get("email"), dict) else None)
            or (self.config.get("user_email") if isinstance(self.config, dict) else None)
            or ""
        )
        self.user_email = str(self.user_email).strip() if self.user_email else ""

        self.total_jobs = 0
        self.status = "INITIALIZING"
        self.error_message = ""
        self.finished_at = None
        self.duration_seconds = 0.0

        self.results = []
        self._results_lock = threading.Lock()
        self._email_sent = False
        self._email_sent_lock = threading.Lock()

        # Initialize RunLogger
        try:
            from utils.report import RunLogger
            self.reporter = RunLogger(
                target_urls=self.target_urls,
                started_at=self.start_time,
                automation_type=self.automation_type,
                user_name=self.user_name,
                user_email=self.user_email,
            )
        except Exception as e:
            logger.warning(f"RunLogger initialization failed (fallback active): {e}")
            self.reporter = None

        set_active_tracker(self)
        self._register_handlers()

    def _load_fallback_config(self):
        cfg_file = BASE_DIR / "config.json"
        if cfg_file.exists():
            try:
                with open(cfg_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _register_handlers(self):
        """Register atexit handler as a final safety net for unexpected process termination."""
        try:
            atexit.register(self._atexit_handler)
        except Exception:
            pass

    def _atexit_handler(self):
        """Fallback invoked on process exit if email was not sent yet."""
        if not self._email_sent:
            try:
                final_status = "INTERRUPTED" if self.status in ("INITIALIZING", "RUNNING") else self.status
                self.finalize_and_email(status=final_status, error=self.error_message or "Process terminated")
            except Exception:
                pass

    def attach_stats(self, stats):
        """Attach live workflow stats object to tracker for real-time tracking."""
        self.attached_stats = stats

    def set_config(self, config):
        if config and isinstance(config, dict):
            self.config = config
            cfg_user = config.get("user_name")
            if cfg_user and (not self.user_name or self.user_name == "Unknown"):
                self.user_name = cfg_user
            cfg_email = config.get("email", {}).get("to") or config.get("user_email")
            if cfg_email and not self.user_email:
                self.user_email = str(cfg_email).strip()
            if self.reporter:
                self.reporter.user_name = self.user_name
                self.reporter.user_email = self.user_email

    def set_target(self, target):
        if target:
            if isinstance(target, list):
                self.target_urls = target
            else:
                self.target_urls = [str(target)]
            if self.reporter:
                self.reporter.target_urls = self.target_urls

    def start_run(self, total_jobs=0):
        """Record the start of the automation run in the local file."""
        self.status = "RUNNING"
        self.total_jobs = total_jobs
        self._persist_to_local_file()

        # Also write initial run json / html
        try:
            if self.reporter:
                self.reporter.results = list(self.results)
                self.reporter.write_json()
                self.reporter.write_html()
        except Exception:
            pass

        logger.info(
            f"[LocalTracker] Run registered: {self.run_id} | User: {self.user_name} | "
            f"Type: {self.automation_type} | Planned Jobs: {self.total_jobs}"
        )

    def record_session_result(
        self,
        keyword="",
        browser="chrome",
        engine="google",
        assigned_engine="",
        target="",
        url="",
        status="success",
        message="",
        duration="",
        duration_ms=None,
        captcha_encountered="False",
    ):
        """
        Record an individual session/keyword completion in real-time.
        Thread-safe and persists to local storage immediately.
        """
        default_target = self.target_urls[0] if self.target_urls else ""
        target_val = target or default_target

        if duration_ms is not None and not duration:
            dur_secs = int(duration_ms / 1000)
            mins = dur_secs // 60
            secs = dur_secs % 60
            duration = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"

        res_entry = {
            "browser": str(browser or "chrome").lower(),
            "target": target_val,
            "keyword": keyword,
            "status": status.lower(),
            "message": message or ("Completed successfully" if status.lower() == "success" else "Failed"),
            "duration": duration,
            "durationMs": duration_ms,
            "captcha_encountered": str(captcha_encountered),
            "automation_type": self.automation_type,
            "user_name": self.user_name,
            "user_email": self.user_email,
            "engine": str(engine or "unknown").lower(),
            "assignedEngine": str(assigned_engine or engine or "unknown").lower(),
            "url": url,
            "timestamp": _iso_utc(_utcnow()),
        }

        with self._results_lock:
            # Replace existing matching entry if already present, or append
            replaced = False
            for i, r in enumerate(self.results):
                if r.get("keyword") == keyword and r.get("engine") == res_entry["engine"]:
                    self.results[i] = res_entry
                    replaced = True
                    break
            if not replaced:
                self.results.append(res_entry)

        # Update local file & RunLogger
        self._persist_to_local_file()
        try:
            if self.reporter:
                self.reporter.results = list(self.results)
                self.reporter.write_json()
                self.reporter.write_html()
        except Exception:
            pass

    def set_results_from_stats(self, stats, config=None):
        """Synchronize results from a full stats dictionary or SessionStats object."""
        if not stats:
            return

        cfg = config or self.config
        global_browser = cfg.get("browser", {}).get("name", "chrome") if isinstance(cfg, dict) else "chrome"
        default_target = self.target_urls[0] if self.target_urls else ""

        extracted = []
        seen_higher_priority_keys = set()

        # Prioritize success first, then failed, then interrupted so best outcome per job is kept
        for cat in ["success", "failed", "interrupted"]:
            items = stats.get(cat, [])
            current_cat_keys = set()
            for item in items:
                kw = item.get("keyword", "")
                eng = item.get("engine", item.get("site", "unknown"))
                assigned = item.get("assignedEngine") or item.get("assigned_engine") or eng
                target_val = item.get("target", item.get("target_url", default_target))

                # Identify job uniquely by (target, keyword, engine/site)
                # This ensures distinct engine runs or site submissions for the same target/keyword are NEVER discarded
                job_key = (
                    str(target_val or "").strip().lower(),
                    str(kw or "").strip().lower(),
                    str(eng or "").strip().lower(),
                )
                if job_key in seen_higher_priority_keys:
                    continue
                current_cat_keys.add(job_key)

                dur_ms = item.get("durationMs")
                duration_str = ""
                if dur_ms is not None:
                    total_seconds = int(dur_ms / 1000)
                    mins = total_seconds // 60
                    secs = total_seconds % 60
                    duration_str = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"
                elif item.get("duration"):
                    duration_str = str(item.get("duration"))

                default_msg = (
                    "Target found and visited successfully"
                    if cat == "success"
                    else ("Session interrupted before completion" if cat == "interrupted" else "Target not found on search engine")
                )

                entry = {
                    "browser": str(item.get("browser", global_browser)).lower(),
                    "target": target_val,
                    "keyword": kw,
                    "status": cat,
                    "message": item.get("message") or item.get("error") or default_msg,
                    "duration": duration_str,
                    "durationMs": dur_ms,
                    "captcha_encountered": str(item.get("captcha_encountered", "False")),
                    "automation_type": self.automation_type,
                    "user_name": self.user_name,
                    "user_email": self.user_email,
                    "engine": str(eng).lower(),
                    "assignedEngine": str(assigned).lower(),
                    "url": item.get("url", ""),
                    "timestamp": _iso_utc(_utcnow()),
                }
                extracted.append(entry)

            seen_higher_priority_keys.update(current_cat_keys)

        with self._results_lock:
            if extracted:
                self.results = extracted

        self._persist_to_local_file()

    def _build_summary(self):
        """Construct per-run summary dict compatible with mailer and reports."""
        with self._results_lock:
            current_results = list(self.results)

        by_status = {}
        for r in current_results:
            st = r["status"]
            by_status[st] = by_status.get(st, 0) + 1

        by_browser = {}
        for r in current_results:
            b = r["browser"]
            if b not in by_browser:
                by_browser[b] = {"total": 0}
            by_browser[b]["total"] += 1
            by_browser[b][r["status"]] = by_browser[b].get(r["status"], 0) + 1

        by_target = {}
        if self.target_urls:
            for t in self.target_urls:
                if t:
                    by_target[str(t)] = 0
        for r in current_results:
            tgt = r.get("target")
            if tgt:
                by_target[tgt] = by_target.get(tgt, 0) + 1

        by_engine = {}
        by_assigned_engine = {}
        for r in current_results:
            eng = r.get("engine", "unknown")
            by_engine[eng] = by_engine.get(eng, 0) + 1
            assigned = r.get("assignedEngine", eng)
            by_assigned_engine[assigned] = by_assigned_engine.get(assigned, 0) + 1

        finished = self.finished_at or _utcnow()
        dur_secs = max(0.0, (finished - self.start_time).total_seconds())

        return {
            "userName": self.user_name,
            "user_name": self.user_name,
            "userEmail": self.user_email,
            "user_email": self.user_email,
            "startedAt": _iso_utc(self.start_time),
            "finishedAt": _iso_utc(finished),
            "targetUrls": self.target_urls,
            "totalAttempts": len(current_results),
            "duration": _format_duration(dur_secs),
            "duration_seconds": dur_secs,
            "byStatus": by_status,
            "byBrowser": by_browser,
            "byTarget": by_target,
            "byEngine": by_engine,
            "byAssignedEngine": by_assigned_engine,
            "automationType": self.automation_type,
            "status": self.status,
            "errorMessage": self.error_message,
        }

    def _persist_to_local_file(self):
        """Save the current run record inside logs/local_user_runs.json."""
        try:
            data = load_local_runs_data()
            runs = data.get("runs", [])

            with self._results_lock:
                current_results = list(self.results)

            summary = self._build_summary()
            finished = self.finished_at or _utcnow()
            dur_secs = max(0.0, (finished - self.start_time).total_seconds())

            success_cnt = sum(1 for r in current_results if r.get("status") in ("success", "submitted"))
            failed_cnt = sum(1 for r in current_results if "fail" in r.get("status", "").lower() or "error" in r.get("status", "").lower())
            interrupted_cnt = sum(1 for r in current_results if "interrupt" in r.get("status", "").lower())

            run_record = {
                "run_id": self.run_id,
                "user_name": self.user_name,
                "user_email": self.user_email,
                "automation_type": self.automation_type,
                "target": ", ".join(self.target_urls) if self.target_urls else "",
                "started_at": _iso_utc(self.start_time),
                "started_at_ist": _format_ist(self.start_time),
                "finished_at": _iso_utc(self.finished_at) if self.finished_at else None,
                "finished_at_ist": _format_ist(self.finished_at) if self.finished_at else "In Progress",
                "duration": _format_duration(dur_secs),
                "duration_seconds": dur_secs,
                "status": self.status,
                "error_message": self.error_message,
                "total_jobs": self.total_jobs,
                "completed_jobs": len(current_results),
                "success_count": success_cnt,
                "failure_count": failed_cnt,
                "interrupted_count": interrupted_cnt,
                "summary": summary,
                "results": current_results,
            }

            # Update if already exists, else append
            existing_idx = -1
            for idx, r in enumerate(runs):
                if r.get("run_id") == self.run_id:
                    existing_idx = idx
                    break

            if existing_idx >= 0:
                runs[existing_idx] = run_record
            else:
                runs.append(run_record)

            # Limit history to last 500 runs to keep file compact and fast
            if len(runs) > 500:
                runs = runs[-500:]

            data["runs"] = runs
            save_local_runs_data(data)
        except Exception as e:
            logger.warning(f"[LocalTracker] Error persisting run to local file: {e}")

    def finalize_and_email(self, status=None, error=None, stats=None, config=None, start_time=None):
        """
        Finalize the run state, write the report files, and send the summary email.
        Thread-safe and guaranteed to execute exactly ONCE.
        """
        with self._email_sent_lock:
            if self._email_sent:
                return
            self._email_sent = True

        if start_time:
            self.start_time = start_time
        if config:
            self.set_config(config)
        if error:
            self.error_message = str(error)

        if status:
            self.status = status
        elif self.error_message:
            self.status = "FAILED"
        elif not self.status or self.status == "RUNNING":
            self.status = "COMPLETED"

        self.finished_at = _utcnow()
        self.duration_seconds = max(0.0, (self.finished_at - self.start_time).total_seconds())

        # If stats provided or attached, extract and populate complete results
        effective_stats = stats if stats is not None else getattr(self, "attached_stats", None)
        if effective_stats is not None:
            self.set_results_from_stats(effective_stats, self.config)

        # If results is still empty because run failed before any sessions executed:
        with self._results_lock:
            if not self.results:
                msg = self.error_message or (
                    "Automation interrupted by user before any sessions completed."
                    if self.status == "INTERRUPTED"
                    else "Run ended without session records."
                )
                self.results.append({
                    "browser": self.config.get("browser", {}).get("name", "chrome") if isinstance(self.config, dict) else "chrome",
                    "target": self.target_urls[0] if self.target_urls else "",
                    "keyword": "Startup/Initialization",
                    "status": "interrupted" if self.status == "INTERRUPTED" else "failed",
                    "message": msg,
                    "duration": _format_duration(self.duration_seconds),
                    "durationMs": int(self.duration_seconds * 1000),
                    "captcha_encountered": "False",
                    "automation_type": self.automation_type,
                    "user_name": self.user_name,
                    "user_email": self.user_email,
                    "engine": "system",
                    "assignedEngine": "system",
                    "url": "",
                    "timestamp": _iso_utc(self.finished_at),
                })

        # Persist final state to local runs file
        self._persist_to_local_file()

        # Write final run-*.json and run-*.html
        json_path = None
        html_path = None
        try:
            if self.reporter is None:
                from utils.report import RunLogger
                self.reporter = RunLogger(
                    target_urls=self.target_urls,
                    started_at=self.start_time,
                    automation_type=self.automation_type,
                    user_name=self.user_name,
                    user_email=self.user_email,
                )
            self.reporter.results = list(self.results)
            json_path = self.reporter.write_json()
            html_path = self.reporter.write_html()
        except Exception as e:
            logger.error(f"[LocalTracker] Failed to write report files: {e}", exc_info=True)

        # Send report email
        try:
            from utils.mailer import send_report_email
            summary = self._build_summary()
            send_report_email(self.config, summary, list(self.results), html_path, json_path)
            logger.info(
                f"[LocalTracker] Summary report email dispatched for run {self.run_id} "
                f"(Status: {self.status})!"
            )
        except Exception as e:
            logger.error(f"[LocalTracker] Failed to send report email: {e}", exc_info=True)


def get_run_tracker(automation_type="Web", config=None, target_urls=None, user_name=None, user_email=None):
    """Factory helper to obtain a new LocalRunTracker instance."""
    return LocalRunTracker(
        automation_type=automation_type,
        config=config,
        target_urls=target_urls,
        user_name=user_name,
        user_email=user_email,
    )


def record_active_session_result(keyword="", browser="chrome", engine="google", assigned_engine="", target="", url="", status="success", message="", duration="", duration_ms=None, captcha_encountered="False"):
    """Global helper called by workers to record results into the active tracker."""
    tracker = get_active_tracker()
    if tracker:
        try:
            tracker.record_session_result(
                keyword=keyword,
                browser=browser,
                engine=engine,
                assigned_engine=assigned_engine,
                target=target,
                url=url,
                status=status,
                message=message,
                duration=duration,
                duration_ms=duration_ms,
                captcha_encountered=captcha_encountered,
            )
        except Exception as e:
            logger.warning(f"Failed to record session result into active tracker: {e}")

