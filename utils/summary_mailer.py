"""
utils/summary_mailer.py

Comprehensive 24-Hour Multi-User Summary Email and Excel Report Flow.

Features:
- Collects runs executed in the last 24 hours (or configurable hours) across all users.
- Sources data from MongoDB (automation_runs, automation_logs, backlinks) with automatic
  supplement/fallback from local run logs (logs/run-*.json, logs/fallback_*.json.log).
- Enriches every execution run with:
    * Browser (Chrome, Edge, Firefox, Brave)
    * Destination Visited URL (Target URL / Video watch link)
    * Final Result Message / Outcome / Failure reason
    * Keyword, Search Engine, Assigned Engine, Target Domain/Channel
    * Accurate Duration and Captcha detection status
- Generates a beautifully styled, corporate multi-sheet Excel spreadsheet (.xlsx):
    * Sheet 1: "Summary by User" (KPI cards + table of all users with success/failure counts & rates)
    * Sheet 2: "All Detailed Logs" (Full execution log across all users matching per-run report table)
    * Sheet 3..N: Dedicated Tab per User (e.g. "User - Anjali", "User - Kajol jain") with their complete run logs
    * Sheet Last: "Event Trace Audit Logs" (Timestamped system action logs)
- Executive-grade HTML email with user KPI cards, summary table, and prominent attachment callout.
- Gmail SMTP SSL dispatcher with admin CCs.
"""

import os
import re
import json
import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

DEFAULT_ADMIN_CC = ""
DEFAULT_FALLBACK_TO = "anubhav.abap@gmail.com"


def _parse_iso_utc(val):
    """Safely parse various datetime formats (UTC, IST, ISO, etc.) into UTC datetime."""
    if not val:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            # Datetimes stored in MongoDB BSON Date fields are always UTC
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(val, tz=timezone.utc)
        except Exception:
            return None
    val_str = str(val).strip()
    if not val_str:
        return None

    IST_TZ = timezone(timedelta(hours=5, minutes=30), name="IST")
    if "IST" in val_str:
        clean = val_str.replace(" IST", "").strip()
        for ifmt in ("%d-%m-%Y %I:%M:%S %p", "%d-%m-%Y %H:%M:%S", "%d/%m/%Y %I:%M:%S %p"):
            try:
                dt = datetime.strptime(clean, ifmt)
                return dt.replace(tzinfo=IST_TZ).astimezone(timezone.utc)
            except ValueError:
                pass

    val_clean = val_str.replace(" UTC", "").replace("Z", "+00:00").strip()
    # Try fromisoformat first to preserve timezone offsets like +05:30 accurately
    try:
        dt = datetime.fromisoformat(val_clean)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %I:%M:%S %p",
    ):
        try:
            dt = datetime.strptime(val_clean, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    return None


def format_indian_time(dt):
    if not dt:
        return "N/A"
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        ist_dt = dt.astimezone(timezone(timedelta(hours=5, minutes=30), name="IST"))
        return ist_dt.strftime("%d-%m-%Y %I:%M:%S %p IST")
    return str(dt)


def _format_dt(dt, iso=False):
    return format_indian_time(dt)


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


def _parse_duration_to_seconds(val):
    """Safely parse duration string or numeric value into seconds."""
    if val is None or val == "":
        return 0.0
    if isinstance(val, (int, float)):
        return max(0.0, float(val))
    val_str = str(val).strip()
    if not val_str or val_str.lower() in ("none", "null", "-", "n/a", "unknown"):
        return 0.0

    try:
        return max(0.0, float(val_str))
    except ValueError:
        pass

    # Check for HH:MM:SS or MM:SS
    if ":" in val_str:
        parts = val_str.split(":")
        try:
            if len(parts) == 3:
                return max(0.0, float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2]))
            elif len(parts) == 2:
                return max(0.0, float(parts[0]) * 60 + float(parts[1]))
        except ValueError:
            pass

    hours = 0.0
    minutes = 0.0
    seconds = 0.0

    h_match = re.search(r'(\d+(?:\.\d+)?)\s*h', val_str, re.I)
    if h_match:
        hours = float(h_match.group(1))

    m_match = re.search(r'(\d+(?:\.\d+)?)\s*m(?:in|s)?(?![a-z])', val_str, re.I)
    if m_match:
        minutes = float(m_match.group(1))

    s_match = re.search(r'(\d+(?:\.\d+)?)\s*s(?:ec)?(?![a-z])', val_str, re.I)
    if s_match:
        seconds = float(s_match.group(1))

    total = hours * 3600.0 + minutes * 60.0 + seconds
    return max(0.0, total)


def _format_total_hours(dur_seconds):
    """
    Format total seconds into clean hours & minutes format,
    e.g. '15h 48m', '3h 53m', '0h 11m'.
    """
    if not dur_seconds or dur_seconds <= 0:
        return "0h 0m"
    try:
        total_secs = int(float(dur_seconds))
        hrs = total_secs // 3600
        mins = (total_secs % 3600) // 60
        secs = total_secs % 60
        if hrs > 0 or mins > 0:
            return f"{hrs}h {mins}m"
        elif secs > 0:
            return f"0h 0m {secs}s"
        return "0h 0m"
    except Exception:
        return "0h 0m"


def _sanitize_sheet_name(name, existing_names):
    """Sanitize sheet name for Excel (max 31 chars, invalid chars removed, unique)."""
    clean = re.sub(r'[\\/*?:\[\]]', '_', str(name or "User").strip())
    clean = clean[:28] if len(clean) > 28 else clean
    candidate = clean or "User"
    counter = 1
    while candidate.lower() in [s.lower() for s in existing_names]:
        suffix = f"_{counter}"
        candidate = clean[:31 - len(suffix)] + suffix
        counter += 1
    existing_names.append(candidate)
    return candidate


def compute_user_active_seconds(runs, max_gap_seconds=180, max_run_duration=1800, window_hours=24):
    """
    Calculate the accurate active working duration in seconds for a user across their runs.
    - Uses merged execution intervals so parallel workers/threads do not multiply hours artificially.
    - Merges consecutive runs separated by short pauses (<= max_gap_seconds) into continuous sessions.
    - Prevents runaway / stale runs from inflating time beyond realistic task limits.
    - Strictly bounded by the lookback window (e.g. window_hours * 3600).
    """
    if not runs:
        return 0.0

    intervals = []
    for r in runs:
        s = _parse_iso_utc(r.get("started_at"))
        f = _parse_iso_utc(r.get("finished_at"))
        d_sec = r.get("duration_seconds")
        if not isinstance(d_sec, (int, float)) or d_sec < 0:
            d_sec = _parse_duration_to_seconds(r.get("duration"))

        # Clean/sanitize interval
        if s and f:
            raw_diff = (f - s).total_seconds()
            if raw_diff < 0:
                f = s + timedelta(seconds=max(d_sec or 30.0, 30.0))
            elif raw_diff > max_run_duration:
                if d_sec and 0 < d_sec <= max_run_duration:
                    f = s + timedelta(seconds=d_sec)
                else:
                    f = s + timedelta(seconds=min(raw_diff, 180.0))
        elif s:
            f = s + timedelta(seconds=max(d_sec or 60.0, 30.0))
        elif f:
            s = f - timedelta(seconds=max(d_sec or 60.0, 30.0))
        else:
            continue

        if s and f and f >= s:
            intervals.append((s, f))

    if not intervals:
        fallback_secs = sum(max(0.0, min(float(r.get("duration_seconds") or 0.0), 300.0)) for r in runs)
        return min(fallback_secs, float(window_hours * 3600))

    intervals.sort(key=lambda x: x[0])
    merged = [intervals[0]]
    for cur_s, cur_f in intervals[1:]:
        prev_s, prev_f = merged[-1]
        if cur_s <= prev_f + timedelta(seconds=max_gap_seconds):
            merged[-1] = (prev_s, max(prev_f, cur_f))
        else:
            merged.append((cur_s, cur_f))

    total_active_secs = sum((f - s).total_seconds() for s, f in merged)
    max_window_secs = float(window_hours * 3600)
    return min(total_active_secs, max_window_secs)


def build_user_report_blocks(u):
    """
    Builds the exact post-run email summary blocks for a single user:
      - user_name, user_email, started_at, finished_at, total_attempts
      - by_status dict
      - by_browser dict
      - by_target dict (successful counts)
      - detailed_lines list of tuples: (formatted_line, run_dict)
    """
    runs = u.get("runs", [])

    by_status = {}
    for r in runs:
        st = str(r.get("status") or "unknown").lower()
        by_status[st] = by_status.get(st, 0) + 1

    by_browser = {}
    for r in runs:
        b = str(r.get("browser") or "chrome").lower()
        if b not in by_browser:
            by_browser[b] = {"total": 0}
        by_browser[b]["total"] += 1
        st = str(r.get("status") or "unknown").lower()
        by_browser[b][st] = by_browser[b].get(st, 0) + 1

    successful_by_target = {}
    for r in runs:
        tgt = str(r.get("target") or "Unknown").strip()
        st = str(r.get("status") or "").lower()
        if st in ("success", "submitted"):
            successful_by_target[tgt] = successful_by_target.get(tgt, 0) + 1

    detailed_lines = []
    for r in runs:
        b = str(r.get("browser") or "chrome").lower()
        eng = str(r.get("engine") or "unknown").lower()
        st = str(r.get("status") or "unknown").lower()
        cap = str(r.get("captcha_encountered") or "False")
        kw = str(r.get("keyword") or "").strip()
        tgt = str(r.get("target") or "").strip()
        url = str(r.get("visited_url") or r.get("url") or "").strip()
        url_text = f" ({url})" if url else ""
        line = f"- [{b}] [{eng}] [{st}] [Captcha: {cap}] {kw} -> {tgt}{url_text}"
        detailed_lines.append((line, r))

    # Calculate accurate earliest start and latest finish across all user runs
    all_starts = []
    all_finishes = []
    for r in runs:
        s = _parse_iso_utc(r.get("started_at"))
        if s:
            all_starts.append(s)
        f = _parse_iso_utc(r.get("finished_at"))
        if f:
            all_finishes.append(f)
        elif s:
            all_finishes.append(s)

    first_dt = _parse_iso_utc(u.get("first_run"))
    last_dt = _parse_iso_utc(u.get("last_run"))

    if all_starts:
        min_start = min(all_starts)
        if not first_dt or min_start < first_dt:
            first_dt = min_start

    if all_finishes:
        max_finish = max(all_finishes)
        if not last_dt or max_finish > last_dt:
            last_dt = max_finish

    user_dur_secs = u.get("total_duration_seconds")
    if user_dur_secs is None or user_dur_secs <= 0:
        user_dur_secs = compute_user_active_seconds(runs)

    if user_dur_secs <= 0 and first_dt and last_dt and last_dt >= first_dt:
        user_dur_secs = max(0, int((last_dt - first_dt).total_seconds()))

    total_dur_str = _format_duration(user_dur_secs)

    return {
        "user_name": u.get("user_name", "Unknown"),
        "user_email": u.get("user_email") or "Not configured",
        "started_at": _format_dt(first_dt or u.get("first_run")),
        "finished_at": _format_dt(last_dt or u.get("last_run")),
        "total_duration": total_dur_str,
        "total_duration_seconds": user_dur_secs,
        "total_attempts": u.get("total_runs", len(runs)),
        "by_status": by_status,
        "by_browser": by_browser,
        "by_target": successful_by_target,
        "detailed_lines": detailed_lines,
        "success_rate": u.get("success_rate", 0.0),
        "success_runs": u.get("success_runs", 0),
        "failed_runs": u.get("failed_runs", 0),
        "interrupted_runs": u.get("interrupted_runs", 0),
    }


def fetch_24h_summary_data(hours=24, end_time=None, logs_dir="logs"):
    """
    Collects execution runs and logs within the last `hours` window.
    Merges and enriches data from MongoDB and local log files.
    Returns structured dictionary with summary, users, run_details, and detailed_logs.
    """
    if end_time is None:
        end_time = datetime.now(timezone.utc)
    else:
        end_time = _parse_iso_utc(end_time) or datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=hours)

    base_dir = Path(__file__).resolve().parent.parent
    logs_path = base_dir / logs_dir

    runs_by_id = {}
    detailed_logs = []
    logs_by_run_id = {}

    # 1. Query MongoDB (if available)
    try:
        from utils.database import get_runs_collection, get_logs_collection, check_db_connection
        if check_db_connection():
            runs_col = get_runs_collection()
            mongo_runs = list(runs_col.find(
                {
                    "$or": [
                        {"started_at": {"$gte": start_time - timedelta(hours=1), "$lte": end_time + timedelta(hours=1)}},
                        {"finished_at": {"$gte": start_time - timedelta(hours=1), "$lte": end_time + timedelta(hours=1)}}
                    ]
                },
                {"_id": 0}
            ))

            for doc in mongo_runs:
                s_at = _parse_iso_utc(doc.get("started_at"))
                f_at = _parse_iso_utc(doc.get("finished_at"))
                
                in_window = False
                if s_at and (start_time <= s_at <= end_time):
                    in_window = True
                elif f_at and (start_time <= f_at <= end_time):
                    in_window = True
                if not in_window:
                    continue

                run_id = str(doc.get("run_id") or "")
                if not run_id:
                    continue

                duration_str = ""
                dur_secs = 0.0
                explicit_dur = None
                if doc.get("duration_seconds") is not None:
                    try:
                        explicit_dur = max(0.0, float(doc.get("duration_seconds")))
                    except Exception:
                        pass
                elif doc.get("duration"):
                    explicit_dur = _parse_duration_to_seconds(doc.get("duration"))

                if s_at and f_at:
                    raw_diff = max(0.0, (f_at - s_at).total_seconds())
                    if explicit_dur is not None and 0 < explicit_dur <= 1800:
                        dur_secs = explicit_dur
                    elif raw_diff <= 1800:
                        dur_secs = raw_diff
                    else:
                        dur_secs = min(raw_diff, 180.0)
                    if raw_diff > 1800 and dur_secs > 0:
                        f_at = s_at + timedelta(seconds=dur_secs)
                elif explicit_dur is not None:
                    dur_secs = min(explicit_dur, 1800.0)

                duration_str = _format_duration(dur_secs) if dur_secs > 0 else ""

                status = str(doc.get("status") or "UNKNOWN").upper()
                u_name = str(doc.get("user_name") or "Unknown").strip() or "Unknown"
                u_email = str(doc.get("user_email") or "").strip()
                auto_type = str(doc.get("automation_type") or "Web").capitalize()
                browser = str(doc.get("browser_mode") or doc.get("browser") or "").lower()

                runs_by_id[run_id] = {
                    "run_id": run_id,
                    "user_name": u_name,
                    "user_email": u_email,
                    "automation_type": auto_type,
                    "status": status,
                    "target": str(doc.get("target") or ""),
                    "keyword": str(doc.get("search_keyword") or doc.get("original_keyword") or ""),
                    "engine": str(doc.get("search_engine") or ""),
                    "assigned_engine": str(doc.get("assigned_engine") or doc.get("search_engine") or ""),
                    "flow_type": str(doc.get("flow_type") or ""),
                    "browser": browser,
                    "visited_url": str(doc.get("url") or ""),
                    "started_at": s_at,
                    "finished_at": f_at,
                    "duration": duration_str,
                    "duration_seconds": dur_secs,
                    "captcha_encountered": str(doc.get("captcha_encountered", False)),
                    "outcome_message": "",
                    "error_message": "",
                    "source": "mongodb",
                }

            if runs_by_id:
                logs_col = get_logs_collection()
                run_id_list = list(runs_by_id.keys())
                mongo_logs = list(logs_col.find(
                    {
                        "$or": [
                            {"run_id": {"$in": run_id_list}},
                            {"timestamp": {"$gte": start_time - timedelta(hours=1), "$lte": end_time + timedelta(hours=1)}}
                        ]
                    },
                    {"_id": 0}
                ).sort("timestamp", 1))

                for log_doc in mongo_logs:
                    log_ts = _parse_iso_utc(log_doc.get("timestamp"))
                    r_id = str(log_doc.get("run_id") or "")
                    u_name = runs_by_id.get(r_id, {}).get("user_name", "Unknown") if r_id else "System"

                    entry = {
                        "timestamp": log_ts or log_doc.get("timestamp"),
                        "run_id": r_id,
                        "user_name": u_name,
                        "level": str(log_doc.get("level") or "INFO").upper(),
                        "action": str(log_doc.get("action") or ""),
                        "status": str(log_doc.get("event_status") or ""),
                        "engine": str(log_doc.get("search_engine") or ""),
                        "keyword": str(log_doc.get("keyword") or ""),
                        "url": str(log_doc.get("url") or ""),
                        "message": str(log_doc.get("message") or ""),
                        "error_message": str(log_doc.get("error_message") or ""),
                    }
                    detailed_logs.append(entry)

                    if r_id:
                        if r_id not in logs_by_run_id:
                            logs_by_run_id[r_id] = []
                        logs_by_run_id[r_id].append(entry)

    except Exception as e:
        logger.warning(f"Summary Mailer: Note on MongoDB fetch: {e}")

    # 1.5 Local persistent runs from logs/local_user_runs.json
    local_runs_file = logs_path / "local_user_runs.json"
    if local_runs_file.exists():
        try:
            with open(local_runs_file, "r", encoding="utf-8") as f:
                local_data = json.load(f)
            raw_runs = local_data.get("runs", []) if isinstance(local_data, dict) else (local_data if isinstance(local_data, list) else [])
            for r_entry in raw_runs:
                s_at = _parse_iso_utc(r_entry.get("started_at"))
                f_at = _parse_iso_utc(r_entry.get("finished_at"))
                in_window = False
                if s_at and (start_time <= s_at <= end_time):
                    in_window = True
                elif f_at and (start_time <= f_at <= end_time):
                    in_window = True
                if not in_window:
                    continue

                parent_run_id = str(r_entry.get("run_id") or "")
                u_name = str(r_entry.get("user_name") or "Unknown").strip() or "Unknown"
                u_email = str(r_entry.get("user_email") or "").strip()
                auto_type = str(r_entry.get("automation_type") or "Web").capitalize()
                run_status = str(r_entry.get("status") or "COMPLETED").upper()

                results = r_entry.get("results", [])
                if results:
                    for idx, res in enumerate(results):
                        run_id = f"{parent_run_id}-session-{idx+1}"
                        if run_id in runs_by_id:
                            continue

                        status_raw = str(res.get("status") or "unknown").upper()
                        norm_status = "SUCCESS" if status_raw in ("SUCCESS", "SUBMITTED") else ("INTERRUPTED" if "INTERRUPT" in status_raw else ("FAILED" if "FAIL" in status_raw or "ERROR" in status_raw else status_raw))
                        browser_val = str(res.get("browser") or "chrome").lower()
                        target_val = str(res.get("target") or r_entry.get("target") or "")
                        keyword_val = str(res.get("keyword") or "")
                        engine_val = str(res.get("engine") or res.get("site") or "")
                        assigned_engine_val = str(res.get("assignedEngine") or res.get("engine") or "")
                        url_val = str(res.get("url") or "")
                        msg_val = str(res.get("message") or "")
                        dur_val = str(res.get("duration") or "")
                        dur_secs = 0.0
                        if res.get("durationMs") is not None:
                            try:
                                dur_secs = max(0.0, float(res.get("durationMs")) / 1000.0)
                            except Exception:
                                pass
                        elif dur_val:
                            dur_secs = _parse_duration_to_seconds(dur_val)

                        runs_by_id[run_id] = {
                            "run_id": run_id,
                            "user_name": str(res.get("user_name") or u_name).strip() or "Unknown",
                            "user_email": str(res.get("user_email") or u_email).strip(),
                            "automation_type": str(res.get("automation_type") or auto_type).capitalize(),
                            "status": norm_status,
                            "target": target_val,
                            "keyword": keyword_val,
                            "engine": engine_val,
                            "assigned_engine": assigned_engine_val,
                            "flow_type": "",
                            "browser": browser_val,
                            "visited_url": url_val,
                            "started_at": s_at,
                            "finished_at": f_at or s_at,
                            "duration": dur_val,
                            "duration_seconds": dur_secs,
                            "captcha_encountered": str(res.get("captcha_encountered", "False")),
                            "outcome_message": msg_val or ("Completed successfully" if norm_status == "SUCCESS" else "Failed/Interrupted"),
                            "error_message": msg_val if norm_status != "SUCCESS" else "",
                            "source": "local_history",
                        }

                        log_e = {
                            "timestamp": s_at,
                            "run_id": run_id,
                            "user_name": str(res.get("user_name") or u_name).strip(),
                            "level": "INFO" if norm_status == "SUCCESS" else "ERROR",
                            "action": "automation_execution",
                            "status": norm_status,
                            "engine": engine_val,
                            "keyword": keyword_val,
                            "url": url_val or target_val,
                            "message": f"Run {norm_status} on {engine_val} ({dur_val})",
                            "error_message": msg_val if norm_status != "SUCCESS" else "",
                        }
                        detailed_logs.append(log_e)
                        logs_by_run_id.setdefault(run_id, []).append(log_e)
                elif parent_run_id and parent_run_id not in runs_by_id:
                    runs_by_id[parent_run_id] = {
                        "run_id": parent_run_id,
                        "user_name": u_name,
                        "user_email": u_email,
                        "automation_type": auto_type,
                        "status": run_status,
                        "target": str(r_entry.get("target") or ""),
                        "keyword": "",
                        "engine": "",
                        "assigned_engine": "",
                        "flow_type": "",
                        "browser": "chrome",
                        "visited_url": "",
                        "started_at": s_at,
                        "finished_at": f_at,
                        "duration": str(r_entry.get("duration") or ""),
                        "duration_seconds": float(r_entry.get("duration_seconds") or 0.0),
                        "captcha_encountered": "False",
                        "outcome_message": str(r_entry.get("error_message") or f"Run finished ({run_status})"),
                        "error_message": str(r_entry.get("error_message") or ""),
                        "source": "local_history",
                    }
        except Exception as e:
            logger.warning(f"Summary Mailer: Error reading local runs file {local_runs_file.name}: {e}")

    # 2. Local fallback / supplement from logs/run-*.json
    if logs_path.exists():
        for json_file in sorted(logs_path.glob("run-*.json"), reverse=True):
            try:
                mtime = datetime.fromtimestamp(json_file.stat().st_mtime, tz=timezone.utc)
                if mtime < start_time - timedelta(days=2):
                    continue

                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                summary = data.get("summary", {})
                s_at = _parse_iso_utc(summary.get("startedAt"))
                if not s_at or not (start_time <= s_at <= end_time):
                    continue

                u_name = str(summary.get("userName") or summary.get("user_name") or "Unknown").strip() or "Unknown"
                u_email = str(summary.get("userEmail") or summary.get("user_email") or "").strip()
                auto_type = str(summary.get("automationType") or "Web").capitalize()
                f_at = _parse_iso_utc(summary.get("finishedAt"))

                results = data.get("results", [])
                if results:
                    for idx, res in enumerate(results):
                        run_id = f"{json_file.stem}-session-{idx+1}"
                        if run_id in runs_by_id:
                            continue

                        status_raw = str(res.get("status") or "unknown").upper()
                        norm_status = "SUCCESS" if status_raw in ("SUCCESS", "SUBMITTED") else ("FAILED" if "FAIL" in status_raw else status_raw)
                        browser_val = str(res.get("browser") or "chrome").lower()
                        target_val = str(res.get("target") or "")
                        keyword_val = str(res.get("keyword") or "")
                        engine_val = str(res.get("engine") or res.get("site") or "")
                        assigned_engine_val = str(res.get("assignedEngine") or res.get("engine") or "")
                        url_val = str(res.get("url") or "")
                        msg_val = str(res.get("message") or "")
                        dur_val = str(res.get("duration") or "")
                        dur_secs = 0.0
                        if res.get("durationMs") is not None:
                            try:
                                dur_secs = max(0.0, float(res.get("durationMs")) / 1000.0)
                            except Exception:
                                pass
                        elif res.get("duration_seconds") is not None:
                            try:
                                dur_secs = max(0.0, float(res.get("duration_seconds")))
                            except Exception:
                                pass
                        elif dur_val:
                            dur_secs = _parse_duration_to_seconds(dur_val)

                        if dur_secs == 0.0 and s_at and f_at:
                            total_run_secs = max(0.0, (f_at - s_at).total_seconds())
                            if len(results) == 1:
                                dur_secs = total_run_secs
                            elif total_run_secs > 0:
                                dur_secs = total_run_secs / len(results)

                        if not dur_val and dur_secs > 0:
                            dur_val = _format_duration(dur_secs)

                        captcha_val = str(res.get("captcha_encountered", "False"))

                        runs_by_id[run_id] = {
                            "run_id": run_id,
                            "user_name": str(res.get("user_name") or u_name).strip() or "Unknown",
                            "user_email": str(res.get("user_email") or u_email).strip(),
                            "automation_type": str(res.get("automation_type") or auto_type).capitalize(),
                            "status": norm_status,
                            "target": target_val,
                            "keyword": keyword_val,
                            "engine": engine_val,
                            "assigned_engine": assigned_engine_val,
                            "flow_type": "",
                            "browser": browser_val,
                            "visited_url": url_val,
                            "started_at": s_at,
                            "finished_at": f_at,
                            "duration": dur_val,
                            "duration_seconds": dur_secs,
                            "captcha_encountered": captcha_val,
                            "outcome_message": msg_val or ("Completed successfully" if norm_status == "SUCCESS" else "Failed"),
                            "error_message": msg_val if norm_status != "SUCCESS" else "",
                            "source": "local_json",
                        }

                        log_e = {
                            "timestamp": s_at,
                            "run_id": run_id,
                            "user_name": str(res.get("user_name") or u_name).strip(),
                            "level": "INFO" if norm_status == "SUCCESS" else "ERROR",
                            "action": "automation_execution",
                            "status": norm_status,
                            "engine": engine_val,
                            "keyword": keyword_val,
                            "url": url_val or target_val,
                            "message": f"Run {norm_status} on {engine_val} ({dur_val})",
                            "error_message": msg_val if norm_status != "SUCCESS" else "",
                        }
                        detailed_logs.append(log_e)
                        logs_by_run_id.setdefault(run_id, []).append(log_e)
                else:
                    run_id = json_file.stem
                    if run_id not in runs_by_id:
                        runs_by_id[run_id] = {
                            "run_id": run_id,
                            "user_name": u_name,
                            "user_email": u_email,
                            "automation_type": auto_type,
                            "status": "COMPLETED",
                            "target": ", ".join(summary.get("targetUrls", [])),
                            "keyword": "",
                            "engine": "",
                            "assigned_engine": "",
                            "flow_type": "",
                            "browser": "chrome",
                            "visited_url": "",
                            "started_at": s_at,
                            "finished_at": f_at,
                            "duration": "",
                            "captcha_encountered": "False",
                            "outcome_message": "Run finished",
                            "error_message": "",
                            "source": "local_json",
                        }
            except Exception as e:
                logger.warning(f"Summary Mailer: Error reading local json {json_file.name}: {e}")

    # 3. ENRICH MONGODB RUNS WITH LOG DETAILS
    for r_id, run_record in runs_by_id.items():
        if run_record.get("source") != "mongodb":
            continue

        r_logs = logs_by_run_id.get(r_id, [])
        status = run_record["status"]

        # Browser
        if not run_record["browser"]:
            for l in r_logs:
                msg = l.get("message") or ""
                m = re.search(r'Browser:\s*([a-zA-Z0-9_\-]+)', msg, re.I)
                if m:
                    run_record["browser"] = m.group(1).lower()
                    break
                elif "Browser started:" in msg:
                    run_record["browser"] = msg.split("Browser started:")[-1].strip().lower()
                    break
            if not run_record["browser"]:
                run_record["browser"] = "chrome"

        # Visited URL
        if not run_record["visited_url"]:
            for l in r_logs:
                u = l.get("url") or ""
                if u and u.startswith("http"):
                    if "watch?v=" in u or ("anubhav" in u and "search" not in u):
                        run_record["visited_url"] = u
                        break
            if not run_record["visited_url"]:
                for l in reversed(r_logs):
                    u = l.get("url") or ""
                    if u and u.startswith("http"):
                        run_record["visited_url"] = u
                        break

        # Outcome message
        outcome_found = False
        if status in ("SUCCESS", "SUBMITTED", "COMPLETED"):
            for l in reversed(r_logs):
                act = l.get("action") or ""
                msg = l.get("message") or ""
                if act in ("KEYWORD_COMPLETED", "VIDEO_FOUND", "WATCH_VIDEO", "TARGET_FOUND", "TARGET_VISITED") and msg:
                    run_record["outcome_message"] = msg
                    outcome_found = True
                    break
            if not outcome_found:
                if status == "COMPLETED":
                    run_record["outcome_message"] = "Session finished (COMPLETED)"
                else:
                    run_record["outcome_message"] = "Target found and visited successfully"
        elif "INTERRUPT" in status:
            run_record["outcome_message"] = "Session interrupted before completion"
        elif "RUNNING" in status:
            run_record["outcome_message"] = "Session was active/running at cutoff"
        elif "FAIL" in status or "ERR" in status:
            for l in reversed(r_logs):
                act = l.get("action") or ""
                msg = l.get("message") or ""
                err = l.get("error_message") or ""
                if (act in ("ALL_ENGINES_EXHAUSTED", "VIDEO_NOT_FOUND", "SEARCH_FAILED", "DRIVER_ERROR") or l.get("level") == "ERROR") and (err or msg):
                    run_record["outcome_message"] = err or msg
                    outcome_found = True
                    break
            if not outcome_found:
                run_record["outcome_message"] = "Search exhausted without finding target"
        else:
            run_record["outcome_message"] = f"Session finished ({status})"

        if run_record["captcha_encountered"] in ("False", False, None, ""):
            for l in r_logs:
                if l.get("action") == "CAPTCHA_DETECTED":
                    run_record["captcha_encountered"] = "True"
                    break

        # E) Fill missing MongoDB duration from log timestamps
        if run_record.get("duration_seconds", 0.0) == 0.0 and run_record.get("started_at") and r_logs:
            s_ts = _parse_iso_utc(run_record["started_at"])
            last_l_ts = _parse_iso_utc(r_logs[-1].get("timestamp"))
            if s_ts and last_l_ts and last_l_ts > s_ts:
                d_sec = max(0.0, (last_l_ts - s_ts).total_seconds())
                run_record["duration_seconds"] = d_sec
                run_record["duration"] = _format_duration(d_sec)

    all_runs = sorted(
        runs_by_id.values(),
        key=lambda r: _parse_iso_utc(r.get("started_at")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True
    )

    # 4. Group by User
    users_dict = {}
    for r in all_runs:
        uname = r["user_name"] or "Unknown"
        uemail = r["user_email"] or "Not configured"
        key = uname

        if key not in users_dict:
            users_dict[key] = {
                "user_name": uname,
                "user_email": uemail,
                "total_runs": 0,
                "success_runs": 0,
                "failed_runs": 0,
                "interrupted_runs": 0,
                "total_duration_seconds": 0.0,
                "success_rate": 0.0,
                "first_run": r["started_at"],
                "last_run": r["started_at"],
                "automation_types": set(),
                "targets": set(),
                "runs": [],
            }

        u = users_dict[key]
        if uemail and u["user_email"] == "Not configured":
            u["user_email"] = uemail

        u["total_runs"] += 1
        # duration calculated accurately below via compute_user_active_seconds
        st = str(r.get("status") or "").upper()
        if st in ("SUCCESS", "SUBMITTED", "COMPLETED"):
            u["success_runs"] += 1
        elif "INTERRUPT" in st or "RUNNING" in st:
            u["interrupted_runs"] += 1
        elif "FAIL" in st or "ERR" in st:
            u["failed_runs"] += 1
        else:
            u["failed_runs"] += 1

        if r["automation_type"]:
            u["automation_types"].add(r["automation_type"])
        if r["target"]:
            u["targets"].add(r["target"])

        cur_ts = _parse_iso_utc(r["started_at"])
        if cur_ts:
            if u["first_run"] is None or cur_ts < _parse_iso_utc(u["first_run"]):
                u["first_run"] = cur_ts
            if u["last_run"] is None or cur_ts > _parse_iso_utc(u["last_run"]):
                u["last_run"] = cur_ts

        u["runs"].append(r)

    users_summary_list = []
    total_successful_runs = 0
    total_failed_runs = 0
    total_interrupted_runs = 0
    total_duration_all_users = 0.0
    automation_type_counts = {}

    for u in users_dict.values():
        total = u["total_runs"]
        succ = u["success_runs"]
        u["success_rate"] = round((succ / total * 100.0), 1) if total > 0 else 0.0
        u["automation_types_str"] = ", ".join(sorted(u["automation_types"])) if u["automation_types"] else "Web"
        u["targets_str"] = ", ".join(sorted(u["targets"])[:5]) if u["targets"] else "N/A"

        # Calculate ACCURATE active duration across user runs using merged intervals
        active_secs = compute_user_active_seconds(u.get("runs", []), window_hours=hours)
        u["total_duration_seconds"] = active_secs
        u["total_hours"] = round(active_secs / 3600.0, 2)
        u["total_hours_formatted"] = _format_total_hours(active_secs)
        total_duration_all_users += active_secs

        total_successful_runs += succ
        total_failed_runs += u["failed_runs"]
        total_interrupted_runs += u["interrupted_runs"]

        for auto_t in u["automation_types"]:
            automation_type_counts[auto_t] = automation_type_counts.get(auto_t, 0) + 1

        # Build post-run format report block for this user
        u["report_block"] = build_user_report_blocks(u)
        users_summary_list.append(u)

    users_summary_list.sort(key=lambda x: x["total_runs"], reverse=True)

    total_runs_count = len(all_runs)
    overall_success_rate = round((total_successful_runs / total_runs_count * 100.0), 1) if total_runs_count > 0 else 0.0

    detailed_logs.sort(
        key=lambda l: _parse_iso_utc(l.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True
    )

    report_data = {
        "summary": {
            "time_window_hours": hours,
            "start_time": start_time,
            "end_time": end_time,
            "start_time_str": _format_dt(start_time),
            "end_time_str": _format_dt(end_time),
            "total_users": len(users_summary_list),
            "total_runs": total_runs_count,
            "total_success": total_successful_runs,
            "total_failed": total_failed_runs,
            "total_interrupted": total_interrupted_runs,
            "total_duration_seconds": total_duration_all_users,
            "total_hours": round(total_duration_all_users / 3600.0, 2),
            "total_hours_formatted": _format_total_hours(total_duration_all_users),
            "overall_success_rate": overall_success_rate,
            "automation_type_counts": automation_type_counts,
        },
        "users": users_summary_list,
        "runs": all_runs,
        "logs": detailed_logs,
    }
    return report_data


def create_summary_excel_report(report_data, output_file_path=None, logs_dir="logs"):
    """
    Generates the Excel report with the exact post-run format for every user:
      - Sheet 1: "Detailed Reports by User" (The default active sheet with complete per-user blocks & links!)
      - Sheet 2..N: Dedicated Tab for each User
      - Sheet N+1: "Master Run Logs" (All runs in pure table format)
      - Sheet Last: "Event Trace Audit Logs" (Chronological logs)
    """
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    base_dir = Path(__file__).resolve().parent.parent
    logs_path = base_dir / logs_dir
    logs_path.mkdir(parents=True, exist_ok=True)

    summary = report_data["summary"]
    users = report_data["users"]
    runs = report_data["runs"]
    logs = report_data["logs"]

    if not output_file_path:
        timestamp_str = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
        output_file_path = logs_path / f"summary_report_24h_{timestamp_str}.xlsx"
    else:
        output_file_path = Path(output_file_path)

    wb = openpyxl.Workbook()

    # Style constants
    FONT_FAMILY = "Segoe UI"
    NAVY_FILL = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    ACCENT_FILL = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")
    USER_BANNER_FILL = PatternFill(start_color="0F766E", end_color="0F766E", fill_type="solid")  # Teal
    SUBHEADER_FILL = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
    LIGHT_GRAY_FILL = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

    TITLE_FONT = Font(name=FONT_FAMILY, size=13, bold=True, color="FFFFFF")
    USER_BANNER_FONT = Font(name=FONT_FAMILY, size=12, bold=True, color="FFFFFF")
    HEADER_FONT = Font(name=FONT_FAMILY, size=10, bold=True, color="FFFFFF")
    SECTION_HEADER_FONT = Font(name=FONT_FAMILY, size=11, bold=True, color="1E3A8A")
    BOLD_FONT = Font(name=FONT_FAMILY, size=10, bold=True, color="1E293B")
    REGULAR_FONT = Font(name=FONT_FAMILY, size=10, color="1E293B")
    MONO_FONT = Font(name="Consolas", size=9.5, color="1E293B")
    URL_FONT = Font(name=FONT_FAMILY, size=10, color="2563EB", underline="single")

    SUCCESS_FILL = PatternFill(start_color="D1FAE5", end_color="D1FAE5", fill_type="solid")
    SUCCESS_FONT = Font(name=FONT_FAMILY, size=10, bold=True, color="065F46")
    FAILED_FILL = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")
    FAILED_FONT = Font(name=FONT_FAMILY, size=10, bold=True, color="991B1B")
    WARN_FILL = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")
    WARN_FONT = Font(name=FONT_FAMILY, size=10, bold=True, color="92400E")

    THIN_BORDER_SIDE = Side(style="thin", color="CBD5E1")
    BORDER_ALL = Border(left=THIN_BORDER_SIDE, right=THIN_BORDER_SIDE, top=THIN_BORDER_SIDE, bottom=THIN_BORDER_SIDE)
    TOP_THICK = Border(top=Side(style="medium", color="1E3A8A"), bottom=Side(style="double", color="1E3A8A"))

    used_sheet_names = []

    # =========================================================================
    # SHEET 1: DETAILED REPORTS BY USER (The default active sheet that opens!)
    # =========================================================================
    ws_main = wb.active
    ws_main.title = "Detailed Reports by User"
    used_sheet_names.append("Detailed Reports by User")
    ws_main.views.sheetView[0].showGridLines = True

    # 1. Title Banner
    ws_main.merge_cells("A1:L1")
    title_cell = ws_main["A1"]
    title_cell.value = "SEO AUTOMATION - 24-HOUR MULTI-USER PERFORMANCE REPORT"
    title_cell.font = TITLE_FONT
    title_cell.fill = NAVY_FILL
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws_main.row_dimensions[1].height = 36

    # 2. Metadata Subheading
    ws_main.merge_cells("A2:L2")
    sub_cell = ws_main["A2"]
    sub_cell.value = (
        f"Window: {summary['start_time_str']} to {summary['end_time_str']} | "
        f"Active Users: {summary['total_users']} | "
        f"Total Runs: {summary['total_runs']} | "
        f"Total Hours: {summary.get('total_hours_formatted', '0h 0m')} | "
        f"Overall Success Rate: {summary['overall_success_rate']}%"
    )
    sub_cell.font = Font(name=FONT_FAMILY, size=10, italic=True, color="E2E8F0")
    sub_cell.fill = ACCENT_FILL
    sub_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws_main.row_dimensions[2].height = 24

    ws_main.row_dimensions[3].height = 8

    # 3. Quick Overview Table
    summary_headers = [
        "User Name",
        "Email Address",
        "Total Runs",
        "Success Runs",
        "Failed Runs",
        "Interrupted",
        "Success Rate (%)",
        "Total Hours",
        "Total Duration",
        "First Active (IST)",
        "Last Active (IST)",
        "Automations Run",
    ]
    ws_main.row_dimensions[4].height = 26
    for col_idx, h_text in enumerate(summary_headers, start=1):
        c = ws_main.cell(row=4, column=col_idx, value=h_text)
        c.font = HEADER_FONT
        c.fill = NAVY_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = BORDER_ALL

    current_row = 5
    total_all_dur_secs = 0
    if not users:
        ws_main.merge_cells("A5:L5")
        no_data_cell = ws_main["A5"]
        no_data_cell.value = "No user automation runs recorded in the last 24 hours."
        no_data_cell.font = Font(name=FONT_FAMILY, size=11, italic=True, color="64748B")
        no_data_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws_main.row_dimensions[5].height = 26
        current_row = 6
    else:
        for idx, u in enumerate(users):
            ws_main.row_dimensions[current_row].height = 22
            row_fill = LIGHT_GRAY_FILL if idx % 2 == 1 else PatternFill(fill_type=None)

            blk = u.get("report_block") or {}
            u_dur = blk.get("total_duration") or "0s"
            total_all_dur_secs += blk.get("total_duration_seconds", 0)

            ws_main.cell(row=current_row, column=1, value=u["user_name"]).font = BOLD_FONT
            ws_main.cell(row=current_row, column=2, value=u["user_email"]).font = REGULAR_FONT
            ws_main.cell(row=current_row, column=3, value=u["total_runs"]).font = BOLD_FONT
            ws_main.cell(row=current_row, column=4, value=u["success_runs"]).font = SUCCESS_FONT
            ws_main.cell(row=current_row, column=5, value=u["failed_runs"]).font = FAILED_FONT
            ws_main.cell(row=current_row, column=6, value=u["interrupted_runs"]).font = WARN_FONT

            c7 = ws_main.cell(row=current_row, column=7, value=f"{u['success_rate']}%")
            if u["success_rate"] >= 80.0:
                c7.font = SUCCESS_FONT; c7.fill = SUCCESS_FILL
            elif u["success_rate"] >= 50.0:
                c7.font = WARN_FONT; c7.fill = WARN_FILL
            else:
                c7.font = FAILED_FONT; c7.fill = FAILED_FILL
            c7.alignment = Alignment(horizontal="center", vertical="center")

            c8 = ws_main.cell(row=current_row, column=8, value=u.get("total_hours_formatted", "0h 0m"))
            c8.font = BOLD_FONT
            c8.alignment = Alignment(horizontal="center", vertical="center")

            c9 = ws_main.cell(row=current_row, column=9, value=u_dur)
            c9.font = REGULAR_FONT
            c9.alignment = Alignment(horizontal="center", vertical="center")

            ws_main.cell(row=current_row, column=10, value=_format_dt(u["first_run"])).font = REGULAR_FONT
            ws_main.cell(row=current_row, column=11, value=_format_dt(u["last_run"])).font = REGULAR_FONT
            ws_main.cell(row=current_row, column=12, value=u["automation_types_str"]).font = REGULAR_FONT

            for col_i in range(1, 13):
                cell = ws_main.cell(row=current_row, column=col_i)
                cell.border = BORDER_ALL
                if col_i != 7 and row_fill.fill_type:
                    cell.fill = row_fill

            current_row += 1

    # TOTAL ROW
    ws_main.row_dimensions[current_row].height = 22
    ws_main.cell(row=current_row, column=1, value="TOTAL").font = BOLD_FONT
    ws_main.cell(row=current_row, column=2, value="")
    ws_main.cell(row=current_row, column=3, value=summary["total_runs"]).font = BOLD_FONT
    ws_main.cell(row=current_row, column=4, value=summary["total_success"]).font = SUCCESS_FONT
    ws_main.cell(row=current_row, column=5, value=summary["total_failed"]).font = FAILED_FONT
    ws_main.cell(row=current_row, column=6, value=summary["total_interrupted"]).font = WARN_FONT
    ws_main.cell(row=current_row, column=7, value=f"{summary['overall_success_rate']}%").font = BOLD_FONT
    ws_main.cell(row=current_row, column=8, value=summary.get("total_hours_formatted", "0h 0m")).font = BOLD_FONT
    ws_main.cell(row=current_row, column=9, value=_format_duration(total_all_dur_secs)).font = BOLD_FONT
    for col_i in range(3, 10):
        ws_main.cell(row=current_row, column=col_i).alignment = Alignment(horizontal="center", vertical="center")
    for col_i in range(1, 13):
        cell = ws_main.cell(row=current_row, column=col_i)
        cell.border = TOP_THICK
        cell.fill = SUBHEADER_FILL
    current_row += 2

    # 4. FOR EVERY USER: RENDER THEIR COMPLETE DETAILED SUMMARY REPORT!
    detail_table_headers = [
        "Detailed Session Target Link (Full Line)",
        "Browser",
        "Engine",
        "Status",
        "Captcha",
        "Keyword",
        "Target",
        "Visited Destination URL",
        "Duration",
        "Result Message / Outcome",
    ]

    for u in users:
        blk = u.get("report_block") or build_user_report_blocks(u)
        uname = blk["user_name"]

        # --- A) USER BANNER ---
        ws_main.row_dimensions[current_row].height = 28
        ws_main.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=10)
        u_banner = ws_main.cell(row=current_row, column=1)
        u_banner.value = (
            f"USER: {uname.upper()} - {blk['total_attempts']} Attempts | "
            f"{blk['success_runs']} Success, {blk['failed_runs']} Failed, {blk['interrupted_runs']} Interrupted "
            f"({blk['success_rate']}% Success Rate)"
        )
        u_banner.font = USER_BANNER_FONT
        u_banner.fill = USER_BANNER_FILL
        u_banner.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        current_row += 1

        # --- B) EXACT EMAIL METADATA BLOCK ---
        meta_items = [
            f"User: {blk['user_name']}",
            f"Email: {blk['user_email']}",
            f"Started: {blk['started_at']}",
            f"Finished: {blk['finished_at']}",
            f"Total duration: {blk['total_duration']}",
            f"Total attempts: {blk['total_attempts']}",
        ]
        for m_line in meta_items:
            ws_main.row_dimensions[current_row].height = 18
            ws_main.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=10)
            c = ws_main.cell(row=current_row, column=1, value=m_line)
            c.font = MONO_FONT
            c.alignment = Alignment(horizontal="left", vertical="center", indent=1)
            current_row += 1

        # By status:
        ws_main.row_dimensions[current_row].height = 18
        ws_main.cell(row=current_row, column=1, value="By status:").font = BOLD_FONT
        current_row += 1
        for st_name, st_cnt in blk["by_status"].items():
            ws_main.row_dimensions[current_row].height = 18
            ws_main.cell(row=current_row, column=1, value=f"{st_name}: {st_cnt}").font = MONO_FONT
            current_row += 1

        # By browser:
        ws_main.row_dimensions[current_row].height = 18
        ws_main.cell(row=current_row, column=1, value="By browser:").font = BOLD_FONT
        current_row += 1
        for b_name, b_stats in blk["by_browser"].items():
            parts = ", ".join(f"{k}: {v}" for k, v in b_stats.items() if k != "total")
            tot = b_stats.get("total", 0)
            ws_main.row_dimensions[current_row].height = 18
            ws_main.cell(row=current_row, column=1, value=f"{b_name}: {tot} attempted ({parts})").font = MONO_FONT
            current_row += 1

        # By target link:
        ws_main.row_dimensions[current_row].height = 18
        ws_main.cell(row=current_row, column=1, value="By target link:").font = BOLD_FONT
        current_row += 1
        for tgt_url, succ_cnt in blk["by_target"].items():
            ws_main.row_dimensions[current_row].height = 18
            ws_main.cell(row=current_row, column=1, value=f"{tgt_url}: {succ_cnt} successful").font = MONO_FONT
            current_row += 1

        # Detailed Session Target Links Header
        ws_main.row_dimensions[current_row].height = 24
        ws_main.cell(row=current_row, column=1, value="Detailed Session Target Links:").font = SECTION_HEADER_FONT
        current_row += 1

        # Detailed Table Headers
        ws_main.row_dimensions[current_row].height = 24
        for col_idx, h_text in enumerate(detail_table_headers, start=1):
            c = ws_main.cell(row=current_row, column=col_idx, value=h_text)
            c.font = HEADER_FONT
            c.fill = NAVY_FILL
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border = BORDER_ALL
        current_row += 1

        # Detailed Session Target Links Rows
        d_lines = blk["detailed_lines"]
        if not d_lines:
            ws_main.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=10)
            c = ws_main.cell(row=current_row, column=1, value="No detailed target links recorded.")
            c.font = Font(name=FONT_FAMILY, size=10, italic=True, color="64748B")
            current_row += 1
        else:
            for d_idx, (fmt_line, r) in enumerate(d_lines):
                ws_main.row_dimensions[current_row].height = 20
                row_fill = LIGHT_GRAY_FILL if d_idx % 2 == 1 else PatternFill(fill_type=None)

                # Col 1: Full formatted text line
                c1 = ws_main.cell(row=current_row, column=1, value=fmt_line)
                c1.font = MONO_FONT
                c1.alignment = Alignment(horizontal="left", vertical="center")

                # Col 2: Browser
                c2 = ws_main.cell(row=current_row, column=2, value=r.get("browser", "chrome"))
                c2.font = REGULAR_FONT
                c2.alignment = Alignment(horizontal="center", vertical="center")

                # Col 3: Engine
                c3 = ws_main.cell(row=current_row, column=3, value=r.get("engine", ""))
                c3.font = REGULAR_FONT
                c3.alignment = Alignment(horizontal="center", vertical="center")

                # Col 4: Status
                st_val = str(r.get("status") or "").upper()
                c4 = ws_main.cell(row=current_row, column=4, value=st_val)
                if st_val in ("SUCCESS", "SUBMITTED", "COMPLETED"):
                    c4.font = SUCCESS_FONT; c4.fill = SUCCESS_FILL
                elif "INTERRUPT" in st_val or "RUNNING" in st_val:
                    c4.font = WARN_FONT; c4.fill = WARN_FILL
                elif "FAIL" in st_val or "ERR" in st_val:
                    c4.font = FAILED_FONT; c4.fill = FAILED_FILL
                else:
                    c4.font = REGULAR_FONT
                c4.alignment = Alignment(horizontal="center", vertical="center")

                # Col 5: Captcha
                c5 = ws_main.cell(row=current_row, column=5, value=str(r.get("captcha_encountered", "False")))
                c5.font = REGULAR_FONT
                c5.alignment = Alignment(horizontal="center", vertical="center")

                # Col 6: Keyword
                c6 = ws_main.cell(row=current_row, column=6, value=r.get("keyword", ""))
                c6.font = REGULAR_FONT
                c6.alignment = Alignment(horizontal="left", vertical="center")

                # Col 7: Target
                c7 = ws_main.cell(row=current_row, column=7, value=r.get("target", ""))
                c7.font = REGULAR_FONT
                c7.alignment = Alignment(horizontal="left", vertical="center")

                # Col 8: Destination URL
                url_v = r.get("visited_url") or r.get("url") or ""
                c8 = ws_main.cell(row=current_row, column=8, value=url_v)
                if url_v and url_v.startswith("http"):
                    c8.font = URL_FONT
                    try:
                        c8.hyperlink = url_v
                    except Exception:
                        pass
                else:
                    c8.font = REGULAR_FONT
                c8.alignment = Alignment(horizontal="left", vertical="center")

                # Col 9: Duration
                c9 = ws_main.cell(row=current_row, column=9, value=r.get("duration", ""))
                c9.font = REGULAR_FONT
                c9.alignment = Alignment(horizontal="center", vertical="center")

                # Col 10: Outcome
                c10 = ws_main.cell(row=current_row, column=10, value=r.get("outcome_message") or r.get("error_message") or "")
                c10.font = REGULAR_FONT
                c10.alignment = Alignment(horizontal="left", vertical="center")

                for col_i in range(1, 11):
                    cell = ws_main.cell(row=current_row, column=col_i)
                    cell.border = BORDER_ALL
                    if col_i != 4 and row_fill.fill_type:
                        cell.fill = row_fill

                current_row += 1

        # Spacer before next user
        current_row += 2

    # Set specific column widths for Sheet 1
    ws_main.column_dimensions["A"].width = 110  # Full line
    ws_main.column_dimensions["B"].width = 14   # Browser
    ws_main.column_dimensions["C"].width = 16   # Engine
    ws_main.column_dimensions["D"].width = 14   # Status
    ws_main.column_dimensions["E"].width = 12   # Captcha
    ws_main.column_dimensions["F"].width = 34   # Keyword
    ws_main.column_dimensions["G"].width = 34   # Target
    ws_main.column_dimensions["H"].width = 44   # Destination URL
    ws_main.column_dimensions["I"].width = 14   # Duration
    ws_main.column_dimensions["J"].width = 38   # Outcome

    # =========================================================================
    # SHEETS 2..N: DEDICATED INDIVIDUAL USER TABS
    # =========================================================================
    for u in users:
        blk = u.get("report_block") or build_user_report_blocks(u)
        u_name = blk["user_name"]
        sheet_title = _sanitize_sheet_name(f"User - {u_name}", used_sheet_names)
        ws_u = wb.create_sheet(title=sheet_title)
        ws_u.views.sheetView[0].showGridLines = True

        u_row = 1
        ws_u.row_dimensions[u_row].height = 30
        ws_u.merge_cells(start_row=u_row, start_column=1, end_row=u_row, end_column=10)
        u_hdr = ws_u.cell(row=u_row, column=1)
        u_hdr.value = (
            f"USER REPORT: {u_name.upper()} - {blk['total_attempts']} Attempts | "
            f"{blk['success_runs']} Success, {blk['failed_runs']} Failed ({blk['success_rate']}% Success Rate)"
        )
        u_hdr.font = USER_BANNER_FONT
        u_hdr.fill = USER_BANNER_FILL
        u_hdr.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        u_row += 1

        meta_items = [
            f"User: {blk['user_name']}",
            f"Email: {blk['user_email']}",
            f"Started: {blk['started_at']}",
            f"Finished: {blk['finished_at']}",
            f"Total duration: {blk['total_duration']}",
            f"Total attempts: {blk['total_attempts']}",
        ]
        for m_line in meta_items:
            ws_u.row_dimensions[u_row].height = 18
            ws_u.merge_cells(start_row=u_row, start_column=1, end_row=u_row, end_column=10)
            c = ws_u.cell(row=u_row, column=1, value=m_line)
            c.font = MONO_FONT
            c.alignment = Alignment(horizontal="left", vertical="center", indent=1)
            u_row += 1

        ws_u.row_dimensions[u_row].height = 18
        ws_u.cell(row=u_row, column=1, value="By status:").font = BOLD_FONT
        u_row += 1
        for st_name, st_cnt in blk["by_status"].items():
            ws_u.row_dimensions[u_row].height = 18
            ws_u.cell(row=u_row, column=1, value=f"{st_name}: {st_cnt}").font = MONO_FONT
            u_row += 1

        ws_u.row_dimensions[u_row].height = 18
        ws_u.cell(row=u_row, column=1, value="By browser:").font = BOLD_FONT
        u_row += 1
        for b_name, b_stats in blk["by_browser"].items():
            parts = ", ".join(f"{k}: {v}" for k, v in b_stats.items() if k != "total")
            tot = b_stats.get("total", 0)
            ws_u.row_dimensions[u_row].height = 18
            ws_u.cell(row=u_row, column=1, value=f"{b_name}: {tot} attempted ({parts})").font = MONO_FONT
            u_row += 1

        ws_u.row_dimensions[u_row].height = 18
        ws_u.cell(row=u_row, column=1, value="By target link:").font = BOLD_FONT
        u_row += 1
        for tgt_url, succ_cnt in blk["by_target"].items():
            ws_u.row_dimensions[u_row].height = 18
            ws_u.cell(row=u_row, column=1, value=f"{tgt_url}: {succ_cnt} successful").font = MONO_FONT
            u_row += 1

        ws_u.row_dimensions[u_row].height = 24
        ws_u.cell(row=u_row, column=1, value="Detailed Session Target Links:").font = SECTION_HEADER_FONT
        u_row += 1

        ws_u.row_dimensions[u_row].height = 24
        for col_idx, h_text in enumerate(detail_table_headers, start=1):
            c = ws_u.cell(row=u_row, column=col_idx, value=h_text)
            c.font = HEADER_FONT
            c.fill = NAVY_FILL
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border = BORDER_ALL
        u_row += 1

        d_lines = blk["detailed_lines"]
        for d_idx, (fmt_line, r) in enumerate(d_lines):
            ws_u.row_dimensions[u_row].height = 20
            row_fill = LIGHT_GRAY_FILL if d_idx % 2 == 1 else PatternFill(fill_type=None)

            c1 = ws_u.cell(row=u_row, column=1, value=fmt_line)
            c1.font = MONO_FONT

            c2 = ws_u.cell(row=u_row, column=2, value=r.get("browser", "chrome"))
            c2.font = REGULAR_FONT
            c2.alignment = Alignment(horizontal="center", vertical="center")

            c3 = ws_u.cell(row=u_row, column=3, value=r.get("engine", ""))
            c3.font = REGULAR_FONT
            c3.alignment = Alignment(horizontal="center", vertical="center")

            st_val = str(r.get("status") or "").upper()
            c4 = ws_u.cell(row=u_row, column=4, value=st_val)
            if st_val in ("SUCCESS", "SUBMITTED", "COMPLETED"):
                c4.font = SUCCESS_FONT; c4.fill = SUCCESS_FILL
            elif "INTERRUPT" in st_val or "RUNNING" in st_val:
                c4.font = WARN_FONT; c4.fill = WARN_FILL
            elif "FAIL" in st_val or "ERR" in st_val:
                c4.font = FAILED_FONT; c4.fill = FAILED_FILL
            else:
                c4.font = REGULAR_FONT
            c4.alignment = Alignment(horizontal="center", vertical="center")

            c5 = ws_u.cell(row=u_row, column=5, value=str(r.get("captcha_encountered", "False")))
            c5.font = REGULAR_FONT
            c5.alignment = Alignment(horizontal="center", vertical="center")

            c6 = ws_u.cell(row=u_row, column=6, value=r.get("keyword", ""))
            c6.font = REGULAR_FONT

            c7 = ws_u.cell(row=u_row, column=7, value=r.get("target", ""))
            c7.font = REGULAR_FONT

            url_v = r.get("visited_url") or r.get("url") or ""
            c8 = ws_u.cell(row=u_row, column=8, value=url_v)
            if url_v and url_v.startswith("http"):
                c8.font = URL_FONT
                try:
                    c8.hyperlink = url_v
                except Exception:
                    pass
            else:
                c8.font = REGULAR_FONT

            c9 = ws_u.cell(row=u_row, column=9, value=r.get("duration", ""))
            c9.font = REGULAR_FONT
            c9.alignment = Alignment(horizontal="center", vertical="center")

            c10 = ws_u.cell(row=u_row, column=10, value=r.get("outcome_message") or r.get("error_message") or "")
            c10.font = REGULAR_FONT

            for col_i in range(1, 11):
                cell = ws_u.cell(row=u_row, column=col_i)
                cell.border = BORDER_ALL
                if col_i != 4 and row_fill.fill_type:
                    cell.fill = row_fill
            u_row += 1

        ws_u.column_dimensions["A"].width = 110
        ws_u.column_dimensions["B"].width = 14
        ws_u.column_dimensions["C"].width = 16
        ws_u.column_dimensions["D"].width = 14
        ws_u.column_dimensions["E"].width = 12
        ws_u.column_dimensions["F"].width = 34
        ws_u.column_dimensions["G"].width = 34
        ws_u.column_dimensions["H"].width = 44
        ws_u.column_dimensions["I"].width = 14
        ws_u.column_dimensions["J"].width = 38

    # =========================================================================
    # SHEET N+1: MASTER RUN LOGS (All runs tabular)
    # =========================================================================
    master_title = _sanitize_sheet_name("Master Run Logs", used_sheet_names)
    ws_master = wb.create_sheet(title=master_title)
    ws_master.views.sheetView[0].showGridLines = True

    master_headers = [
        "User Name",
        "Email Address",
        "Automation Type",
        "Browser",
        "Search Engine",
        "Assigned Engine",
        "Target",
        "Keyword / Query",
        "Status",
        "Result Message / Outcome",
        "Visited Destination URL",
        "Duration",
        "Captcha Encountered",
        "Started At (UTC)",
        "Finished At (UTC)",
        "Run ID",
    ]
    ws_master.row_dimensions[1].height = 26
    for col_idx, h_text in enumerate(master_headers, start=1):
        c = ws_master.cell(row=1, column=col_idx, value=h_text)
        c.font = HEADER_FONT
        c.fill = NAVY_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = BORDER_ALL

    for r_idx, r in enumerate(runs, start=2):
        ws_master.row_dimensions[r_idx].height = 20
        row_fill = LIGHT_GRAY_FILL if r_idx % 2 == 1 else PatternFill(fill_type=None)

        ws_master.cell(row=r_idx, column=1, value=r.get("user_name", "")).font = BOLD_FONT
        ws_master.cell(row=r_idx, column=2, value=r.get("user_email") or "Not configured").font = REGULAR_FONT
        ws_master.cell(row=r_idx, column=3, value=r.get("automation_type", "")).font = REGULAR_FONT
        ws_master.cell(row=r_idx, column=4, value=r.get("browser", "chrome")).font = REGULAR_FONT
        ws_master.cell(row=r_idx, column=5, value=r.get("engine", "")).font = REGULAR_FONT
        ws_master.cell(row=r_idx, column=6, value=r.get("assigned_engine", "")).font = REGULAR_FONT
        ws_master.cell(row=r_idx, column=7, value=r.get("target", "")).font = REGULAR_FONT
        ws_master.cell(row=r_idx, column=8, value=r.get("keyword", "")).font = REGULAR_FONT

        st_val = str(r.get("status") or "").upper()
        c9 = ws_master.cell(row=r_idx, column=9, value=st_val)
        if st_val in ("SUCCESS", "SUBMITTED", "COMPLETED"):
            c9.font = SUCCESS_FONT; c9.fill = SUCCESS_FILL
        elif "INTERRUPT" in st_val or "RUNNING" in st_val:
            c9.font = WARN_FONT; c9.fill = WARN_FILL
        elif "FAIL" in st_val or "ERR" in st_val:
            c9.font = FAILED_FONT; c9.fill = FAILED_FILL
        else:
            c9.font = REGULAR_FONT
        c9.alignment = Alignment(horizontal="center", vertical="center")

        ws_master.cell(row=r_idx, column=10, value=r.get("outcome_message") or r.get("error_message") or "").font = REGULAR_FONT

        url_v = r.get("visited_url") or r.get("url") or ""
        c11 = ws_master.cell(row=r_idx, column=11, value=url_v)
        if url_v and url_v.startswith("http"):
            c11.font = URL_FONT
            try:
                c11.hyperlink = url_v
            except Exception:
                pass
        else:
            c11.font = REGULAR_FONT

        ws_master.cell(row=r_idx, column=12, value=r.get("duration", "")).font = REGULAR_FONT
        ws_master.cell(row=r_idx, column=13, value=str(r.get("captcha_encountered", "False"))).font = REGULAR_FONT
        ws_master.cell(row=r_idx, column=14, value=_format_dt(r.get("started_at"))).font = REGULAR_FONT
        ws_master.cell(row=r_idx, column=15, value=_format_dt(r.get("finished_at"))).font = REGULAR_FONT
        ws_master.cell(row=r_idx, column=16, value=r.get("run_id", "")).font = REGULAR_FONT

        for col_i in range(1, 17):
            cell = ws_master.cell(row=r_idx, column=col_i)
            cell.border = BORDER_ALL
            if col_i != 9 and row_fill.fill_type:
                cell.fill = row_fill

    for col in ws_master.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in list(col)[:200]:
            val_s = str(cell.value or "")
            max_len = max(max_len, len(val_s))
        ws_master.column_dimensions[col_letter].width = min(max(max_len + 4, 12), 48)

    # Save
    wb.save(output_file_path)
    logger.info(f"Summary Mailer: Generated 24h summary Excel report at {output_file_path}")
    return str(output_file_path)


def generate_summary_email_html(report_data):
    """
    Renders the executive HTML email displaying:
      - 24h overview metrics & KPI cards
      - Active users summary table
      - EXACT post-run detailed summary blocks with Detailed Session Target Links for every user!
    """
    summary = report_data["summary"]
    users = report_data["users"]

    def get_rate_color(rate):
        if rate >= 80.0:
            return "#10B981"
        elif rate >= 50.0:
            return "#F59E0B"
        return "#EF4444"

    # User breakdown table
    user_rows_html = ""
    users_detailed_sections_html = ""
    for idx, u in enumerate(users):
        uname = u["user_name"]
        bg_color = "#F8FAFC" if idx % 2 == 1 else "#FFFFFF"
        rate_badge_color = get_rate_color(u["success_rate"])
        total_hours = u.get("total_hours_formatted", "0h 0m")
        blk = u.get("report_block") or {}

        user_rows_html += f"""
        <tr style="background-color: {bg_color}; border-bottom: 1px solid #E2E8F0;">
            <td style="padding: 10px 12px; font-weight: 600; color: #1E293B;">
                {u['user_name']}
            </td>
            <td style="padding: 10px 12px; color: #475569; font-size: 13px;">
                {u['user_email']}
            </td>
            <td style="padding: 10px 12px; text-align: center; font-weight: 600; color: #0F172A;">
                {u['total_runs']}
            </td>
            <td style="padding: 10px 12px; text-align: center; font-weight: 600; color: #10B981;">
                {u['success_runs']}
            </td>
            <td style="padding: 10px 12px; text-align: center; font-weight: 600; color: #EF4444;">
                {u['failed_runs']}
            </td>
            <td style="padding: 10px 12px; text-align: center;">
                <span style="display:inline-block; padding: 3px 8px; border-radius: 9999px; background-color: {rate_badge_color}18; color: {rate_badge_color}; font-weight: 700; font-size: 12px;">
                    {u['success_rate']}%
                </span>
            </td>
            <td style="padding: 10px 12px; text-align: right; font-weight: 600; color: #1E293B; font-size: 13px;">
                {total_hours}
            </td>
        </tr>
        """

        status_lines = "<br>".join(f"&nbsp;&nbsp;{s}: {c}" for s, c in blk.get("by_status", {}).items())

        browser_parts = []
        for b, stats in blk.get("by_browser", {}).items():
            parts = ", ".join(f"{k}: {v}" for k, v in stats.items() if k != "total")
            browser_parts.append(f"&nbsp;&nbsp;{b}: {stats.get('total', 0)} attempted ({parts})")
        browser_lines = "<br>".join(browser_parts)

        target_parts = []
        for tgt, c in blk.get("by_target", {}).items():
            target_parts.append(f"&nbsp;&nbsp;{tgt}: {c} successful")
        target_lines = "<br>".join(target_parts) or "&nbsp;&nbsp;None successful"

        # Show first 20 lines with note if truncated
        d_lines = blk.get("detailed_lines", [])
        displayed_lines = d_lines[:25]
        link_lines_str = "<br>".join(item[0] for item in displayed_lines)
        if len(d_lines) > 25:
            link_lines_str += f"<br><em>... and {len(d_lines) - 25} more detailed session links (see attached Excel file for full list)</em>"

        users_detailed_sections_html += f"""
        <div style="margin-top: 24px; padding: 20px; background-color: #F8FAFC; border: 1px solid #CBD5E1; border-radius: 8px;">
          <div style="font-size: 15px; font-weight: 700; color: #0F766E; margin-bottom: 12px; border-bottom: 2px solid #0F766E; padding-bottom: 6px;">
            Detailed Report: {uname} ({blk['total_attempts']} Attempts | {blk['success_rate']}% Success)
          </div>
          <div style="font-family: Consolas, monospace; font-size: 12.5px; line-height: 1.6; color: #1E293B; background-color: #FFFFFF; padding: 14px; border: 1px solid #E2E8F0; border-radius: 6px;">
            <strong>User:</strong> {blk['user_name']}<br>
            <strong>Email:</strong> {blk['user_email']}<br>
            <strong>Started:</strong> {blk['started_at']}<br>
            <strong>Finished:</strong> {blk['finished_at']}<br>
            <strong>Total duration:</strong> {blk['total_duration']}<br>
            <strong>Total attempts:</strong> {blk['total_attempts']}<br><br>
            <strong>By status:</strong><br>
            {status_lines}<br><br>
            <strong>By browser:</strong><br>
            {browser_lines}<br><br>
            <strong>By target link:</strong><br>
            {target_lines}<br><br>
            <strong>Detailed Session Target Links:</strong><br>
            {link_lines_str}
          </div>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>24-Hour SEO Multi-User Summary Report</title>
</head>
<body style="margin:0; padding:0; background-color:#F1F5F9; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color:#1E293B;">

<table width="100%" cellpadding="0" cellspacing="0" style="background-color:#F1F5F9; padding:24px 0;">
  <tr>
    <td align="center">

      <table width="750" cellpadding="0" cellspacing="0" style="max-width:750px; width:100%; background-color:#FFFFFF; border-radius:12px; overflow:hidden; box-shadow:0 4px 6px -1px rgba(0, 0, 0, 0.08); border:1px solid #E2E8F0;">
        
        <!-- HEADER HERO -->
        <tr>
          <td style="background: linear-gradient(135deg, #1E3A8A 0%, #2563EB 100%); padding: 28px 24px; text-align: left; color:#FFFFFF;">
            <div style="font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px; color: #93C5FD; margin-bottom: 4px;">
              Executive Daily Intelligence
            </div>
            <h1 style="margin: 0; font-size: 22px; font-weight: 800; color:#FFFFFF;">
              24-Hour Multi-User Summary Report
            </h1>
            <p style="margin: 6px 0 0; font-size: 13.5px; color: #DBEAFE;">
              Consolidated execution summary across all users from <strong>{summary['start_time_str']}</strong> to <strong>{summary['end_time_str']}</strong>.
            </p>
          </td>
        </tr>

        <!-- MAIN BODY -->
        <tr>
          <td style="padding: 24px;">

            <!-- KPI STAT CARDS -->
            <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 20px;">
              <tr>
                <td width="20%" style="padding: 3px;">
                  <div style="background-color:#F8FAFC; border:1px solid #E2E8F0; border-radius:6px; padding:12px 8px; text-align:center;">
                    <div style="font-size:11px; font-weight:700; text-transform:uppercase; color:#64748B;">Active Users</div>
                    <div style="font-size:20px; font-weight:800; color:#1E293B; margin-top:2px;">{summary['total_users']}</div>
                  </div>
                </td>
                <td width="20%" style="padding: 3px;">
                  <div style="background-color:#F8FAFC; border:1px solid #E2E8F0; border-radius:6px; padding:12px 8px; text-align:center;">
                    <div style="font-size:11px; font-weight:700; text-transform:uppercase; color:#64748B;">Total Runs</div>
                    <div style="font-size:20px; font-weight:800; color:#2563EB; margin-top:2px;">{summary['total_runs']}</div>
                  </div>
                </td>
                <td width="20%" style="padding: 3px;">
                  <div style="background-color:#F8FAFC; border:1px solid #E2E8F0; border-radius:6px; padding:12px 8px; text-align:center;">
                    <div style="font-size:11px; font-weight:700; text-transform:uppercase; color:#64748B;">Success</div>
                    <div style="font-size:20px; font-weight:800; color:#10B981; margin-top:2px;">{summary['total_success']}</div>
                  </div>
                </td>
                <td width="20%" style="padding: 3px;">
                  <div style="background-color:#F8FAFC; border:1px solid #E2E8F0; border-radius:6px; padding:12px 8px; text-align:center;">
                    <div style="font-size:11px; font-weight:700; text-transform:uppercase; color:#64748B;">Failed</div>
                    <div style="font-size:20px; font-weight:800; color:#EF4444; margin-top:2px;">{summary['total_failed']}</div>
                  </div>
                </td>
                <td width="20%" style="padding: 3px;">
                  <div style="background-color:#F8FAFC; border:1px solid #E2E8F0; border-radius:6px; padding:12px 8px; text-align:center;">
                    <div style="font-size:11px; font-weight:700; text-transform:uppercase; color:#64748B;">Success Rate</div>
                    <div style="font-size:20px; font-weight:800; color:{get_rate_color(summary['overall_success_rate'])}; margin-top:2px;">{summary['overall_success_rate']}%</div>
                  </div>
                </td>
              </tr>
            </table>

            <!-- EXCEL HIGHLIGHT -->
            <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 20px; background-color: #ECFDF5; border: 1px solid #A7F3D0; border-radius: 8px;">
              <tr>
                <td style="padding: 14px 18px;">
                  <div style="font-size: 13.5px; font-weight: 700; color: #065F46;">
                    📊 Downloadable Excel File (.xlsx) Attached
                  </div>
                  <div style="font-size: 12.5px; color: #047857; margin-top: 3px;">
                    The attached workbook contains the complete detailed reports with all <strong>Detailed Session Target Links</strong> for every user, plus dedicated sheets per user!
                  </div>
                </td>
              </tr>
            </table>

            <!-- ACTIVE USERS TABLE -->
            <div style="margin-bottom: 8px;">
              <h2 style="margin: 0; font-size: 15px; font-weight: 700; color: #0F172A;">
                👥 Active Users Summary
              </h2>
            </div>

            <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; width:100%; font-size:12.5px; border:1px solid #CBD5E1; border-radius:6px; overflow:hidden;">
              <thead>
                <tr style="background-color: #1E3A8A; color: #FFFFFF;">
                  <th style="padding: 12px 14px; text-align: left; font-weight: 600;">User Name</th>
                  <th style="padding: 12px 14px; text-align: left; font-weight: 600;">Email</th>
                  <th style="padding: 12px 14px; text-align: center; font-weight: 600;">Total Runs</th>
                  <th style="padding: 12px 14px; text-align: center; font-weight: 600;">Success</th>
                  <th style="padding: 12px 14px; text-align: center; font-weight: 600;">Failed</th>
                  <th style="padding: 12px 14px; text-align: center; font-weight: 600;">Success Rate</th>
                  <th style="padding: 12px 14px; text-align: right; font-weight: 600;">Total Hours</th>
                </tr>
              </thead>
              <tbody>
                {user_rows_html}
              </tbody>
            </table>

            <!-- DETAILED SECTIONS FOR EVERY USER -->
            {users_detailed_sections_html}

          </td>
        </tr>

        <!-- FOOTER -->
        <tr>
          <td style="background-color: #F8FAFC; border-top: 1px solid #E2E8F0; padding: 18px 24px; text-align: center; color: #64748B; font-size: 12px;">
            Automated SEO Reporting Engine &bull; Generated on {summary['end_time_str']}<br>
            Please open the attached Excel file for the full detailed audit spreadsheet.
          </td>
        </tr>

      </table>

    </td>
  </tr>
</table>

</body>
</html>
"""
    return html


def generate_summary_email_text(report_data):
    """Fallback plain text version of the summary report."""
    summary = report_data["summary"]
    users = report_data["users"]

    lines = [
        "==================================================",
        "SEO AUTOMATION - 24-HOUR MULTI-USER SUMMARY REPORT",
        "==================================================",
        f"Period: {summary['start_time_str']} to {summary['end_time_str']}",
        f"Active Users: {summary['total_users']}",
        f"Total Runs:   {summary['total_runs']}",
        f"Successful:   {summary['total_success']}",
        f"Failed:       {summary['total_failed']}",
        f"Success Rate: {summary['overall_success_rate']}%",
        "",
    ]

    for u in users:
        blk = u.get("report_block") or {}
        lines.append(
            f"* {u['user_name']} ({u['user_email']}): "
            f"{u['total_runs']} runs | {u['success_runs']} success | {u['failed_runs']} failed "
            f"({u['success_rate']}% success) | Total hours: {u.get('total_hours_formatted', '0h 0m')}"
        )

        lines.extend(["", "By browser:"])
        for b, stats in blk.get("by_browser", {}).items():
            parts = ", ".join(f"{k}: {v}" for k, v in stats.items() if k != "total")
            lines.append(f"  {b}: {stats.get('total', 0)} attempted ({parts})")

        lines.extend(["", "By target link:"])
        for tgt, c in blk.get("by_target", {}).items():
            lines.append(f"  {tgt}: {c} successful")

        lines.extend(["", "Detailed Session Target Links:"])
        d_lines = blk.get("detailed_lines", [])
        for fmt_line, _ in d_lines[:30]:
            lines.append(fmt_line)
        if len(d_lines) > 30:
            lines.append(f"... and {len(d_lines) - 30} more detailed session links (see attached Excel file)")
        lines.append("")

    lines.extend([
        "==================================================",
        "ATTACHMENT:",
        "The attached Excel file (.xlsx) contains this exact report",
        "for every single user with all detailed session links.",
        "==================================================",
    ])

    return "\n".join(lines)


def send_24h_summary_report(config=None, hours=24, recipient=None, cc=None, save_dir="logs", dry_run=False):
    """
    Main orchestration entry point:
      1. Gathers and enriches runs from last 24 hours across all users.
      2. Generates the downloadable Excel workbook with per-user tabs and complete detailed logs.
      3. Builds the HTML and text email templates.
      4. Dispatches the email with the Excel attachment via Gmail SMTP SSL.
    """
    load_dotenv()

    if config is None:
        base_dir = Path(__file__).resolve().parent.parent
        cfg_file = base_dir / "config.json"
        if cfg_file.exists():
            try:
                with open(cfg_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception:
                config = {}
        else:
            config = {}

    email_cfg = config.get("email", {}) if isinstance(config, dict) else {}
    from_email = email_cfg.get("from", "wednesday.ui5@gmail.com")

    db_email = ""
    try:
        from utils.database import get_user_settings
        settings_doc = get_user_settings()
        if settings_doc:
            db_email = settings_doc.get("email") or settings_doc.get("email_to") or ""
    except Exception:
        pass

    to_email = (
        recipient
        or os.getenv("USER_EMAIL")
        or email_cfg.get("to")
        or db_email
        or DEFAULT_FALLBACK_TO
    )
    to_email = str(to_email).strip() if to_email else DEFAULT_FALLBACK_TO

    cc_email = cc if cc is not None else (email_cfg.get("cc", DEFAULT_ADMIN_CC) or DEFAULT_ADMIN_CC)
    cc_email = str(cc_email).strip() if cc_email else ""
    if cc_email and to_email:
        cc_addrs = [a.strip() for a in cc_email.split(",") if a.strip() and a.strip().lower() != to_email.lower()]
        cc_email = ", ".join(cc_addrs)

    # 1. Gather & enrich data
    logger.info(f"Summary Mailer: Collecting runs and logs for the last {hours} hours...")
    report_data = fetch_24h_summary_data(hours=hours, logs_dir=save_dir)

    # 2. Generate Excel workbook
    excel_path = create_summary_excel_report(report_data, logs_dir=save_dir)
    logger.info(f"Summary Mailer: Excel report generated at {excel_path}")

    # 3. Generate HTML & text bodies
    html_body = generate_summary_email_html(report_data)
    text_body = generate_summary_email_text(report_data)

    if dry_run:
        logger.info(f"Summary Mailer [Dry-Run]: Generated report. Would send to {to_email} (CC: {cc_email}).")
        return {
            "success": True,
            "dry_run": True,
            "excel_path": excel_path,
            "to": to_email,
            "cc": cc_email,
            "summary": report_data["summary"],
            "users_count": len(report_data["users"]),
            "runs_count": len(report_data["runs"]),
        }

    # 4. Check App Password
    app_password = (os.getenv("GMAIL_APP_PASSWORD") or "").strip().replace(" ", "")
    if not app_password:
        msg_err = "Summary email skipped: GMAIL_APP_PASSWORD is not set in environment (.env)."
        logger.warning(msg_err)
        return {
            "success": False,
            "error": msg_err,
            "excel_path": excel_path,
            "to": to_email,
            "summary": report_data["summary"],
        }

    # 5. Build Email Message
    summary = report_data["summary"]
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    subject = (
        f"[SEO Bot] 24-Hour Multi-User Summary - {summary['total_users']} User(s), "
        f"{summary['total_runs']} Runs ({summary['overall_success_rate']}% Success) - {date_str}"
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email
    if cc_email:
        msg["Cc"] = cc_email

    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    # 6. Attach Excel workbook
    try:
        excel_filename = Path(excel_path).name
        with open(excel_path, "rb") as f:
            excel_bytes = f.read()
            msg.add_attachment(
                excel_bytes,
                maintype="application",
                subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                filename=excel_filename,
            )
    except Exception as e:
        logger.error(f"Summary Mailer: Failed to attach Excel file {excel_path}: {e}")
        return {
            "success": False,
            "error": f"Failed to attach Excel file: {e}",
            "excel_path": excel_path,
        }

    # 7. Dispatch via SMTP
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as smtp:
            try:
                smtp.login(from_email, app_password)
            except smtplib.SMTPServerDisconnected as e:
                raise smtplib.SMTPAuthenticationError(
                    535,
                    b"Login rejected: Gmail closed the connection. "
                    b"Regenerate an App Password and update GMAIL_APP_PASSWORD in .env.",
                ) from e
            smtp.send_message(msg)

        logger.info(
            f"Summary Mailer: 24h summary email sent successfully to {to_email} "
            f"(CC: {cc_email}) with attachment {excel_filename}!"
        )
        return {
            "success": True,
            "excel_path": excel_path,
            "to": to_email,
            "cc": cc_email,
            "subject": subject,
            "summary": summary,
        }
    except Exception as e:
        logger.error(f"Summary Mailer: Failed to send 24h summary email: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "excel_path": excel_path,
            "to": to_email,
            "cc": cc_email,
            "summary": summary,
        }
