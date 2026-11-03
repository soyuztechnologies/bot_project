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

DEFAULT_ADMIN_CC = "v86478846@gmail.com, shubhra@soyuztechnologies.com"
DEFAULT_FALLBACK_TO = "v86478846@gmail.com"


def _parse_iso_utc(val):
    """Safely parse various datetime formats into UTC datetime."""
    if not val:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            local_tz = datetime.now().astimezone().tzinfo
            return val.replace(tzinfo=local_tz).astimezone(timezone.utc)
        return val.astimezone(timezone.utc)
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(val, tz=timezone.utc)
        except Exception:
            return None
    val_str = str(val).strip()
    if not val_str:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
    ):
        try:
            dt = datetime.strptime(val_str, fmt)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass
    try:
        val_clean = val_str.replace("Z", "+00:00")
        return datetime.fromisoformat(val_clean).astimezone(timezone.utc)
    except Exception:
        return None


def _format_dt(dt):
    if not dt:
        return ""
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    return str(dt)


def _format_duration(dur_seconds):
    if dur_seconds is None:
        return ""
    try:
        total_secs = int(float(dur_seconds))
        mins = total_secs // 60
        secs = total_secs % 60
        if mins > 0:
            return f"{mins}m {secs}s"
        return f"{secs}s"
    except Exception:
        return str(dur_seconds)


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
            # Find runs started or finished within window
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
                
                # Verify at least start or finish is within the window
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
                if s_at and f_at:
                    dur_secs = max(0, (f_at - s_at).total_seconds())
                    duration_str = _format_duration(dur_secs)

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
                    "captcha_encountered": str(doc.get("captcha_encountered", False)),
                    "outcome_message": "",
                    "error_message": "",
                    "source": "mongodb",
                }

            # Fetch corresponding logs from MongoDB
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
                            "captcha_encountered": captcha_val,
                            "outcome_message": msg_val or ("Completed successfully" if norm_status == "SUCCESS" else "Failed"),
                            "error_message": msg_val if norm_status != "SUCCESS" else "",
                            "source": "local_json",
                        }

                        # Add synthetic log
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

    # 3. ENRICH MONGODB RUNS WITH LOG DETAILS (Browser, Visited URL, Outcome Message)
    for r_id, run_record in runs_by_id.items():
        if run_record.get("source") != "mongodb":
            continue

        r_logs = logs_by_run_id.get(r_id, [])
        status = run_record["status"]

        # A) Detect Browser
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

        # B) Detect Visited URL
        if not run_record["visited_url"]:
            for l in r_logs:
                u = l.get("url") or ""
                if u and u.startswith("http"):
                    # Prioritize YouTube watch URLs or non-search engine destination URLs
                    if "watch?v=" in u or ("anubhav" in u and "search" not in u):
                        run_record["visited_url"] = u
                        break
            if not run_record["visited_url"]:
                # Fallback to any recorded URL
                for l in reversed(r_logs):
                    u = l.get("url") or ""
                    if u and u.startswith("http"):
                        run_record["visited_url"] = u
                        break

        # C) Detect Final Outcome Message / Failure Reason
        outcome_found = False
        if status in ("SUCCESS", "SUBMITTED"):
            for l in reversed(r_logs):
                act = l.get("action") or ""
                msg = l.get("message") or ""
                if act in ("KEYWORD_COMPLETED", "VIDEO_FOUND", "WATCH_VIDEO", "TARGET_FOUND", "TARGET_VISITED") and msg:
                    run_record["outcome_message"] = msg
                    outcome_found = True
                    break
            if not outcome_found:
                run_record["outcome_message"] = "Target found and visited successfully"
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
                run_record["outcome_message"] = "Search exhausted without finding target in search results"
        elif "RUNNING" in status:
            run_record["outcome_message"] = "Session was active/running at cutoff"
        elif "INTERRUPT" in status:
            run_record["outcome_message"] = "Session interrupted before completion"
        else:
            run_record["outcome_message"] = f"Session finished ({status})"

        # D) Captcha Encountered
        if run_record["captcha_encountered"] in ("False", False, None, ""):
            for l in r_logs:
                if l.get("action") == "CAPTCHA_DETECTED":
                    run_record["captcha_encountered"] = "True"
                    break

    # Convert to sorted list (newest first)
    all_runs = sorted(
        runs_by_id.values(),
        key=lambda r: _parse_iso_utc(r.get("started_at")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True
    )

    # 4. Aggregate User Summaries
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
        st = r["status"]
        if st in ("SUCCESS", "SUBMITTED"):
            u["success_runs"] += 1
        elif "FAIL" in st or "ERR" in st:
            u["failed_runs"] += 1
        elif "INTERRUPT" in st:
            u["interrupted_runs"] += 1
        elif "RUNNING" in st:
            u["interrupted_runs"] += 1
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

    # Compute stats
    users_summary_list = []
    total_successful_runs = 0
    total_failed_runs = 0
    total_interrupted_runs = 0
    automation_type_counts = {}

    for u in users_dict.values():
        total = u["total_runs"]
        succ = u["success_runs"]
        u["success_rate"] = round((succ / total * 100.0), 1) if total > 0 else 0.0
        u["automation_types_str"] = ", ".join(sorted(u["automation_types"])) if u["automation_types"] else "Web"
        u["targets_str"] = ", ".join(sorted(u["targets"])[:5]) if u["targets"] else "N/A"
        total_successful_runs += succ
        total_failed_runs += u["failed_runs"]
        total_interrupted_runs += u["interrupted_runs"]

        for auto_t in u["automation_types"]:
            automation_type_counts[auto_t] = automation_type_counts.get(auto_t, 0) + 1

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
    Generates a corporate, multi-tab Excel spreadsheet using openpyxl:
      - Sheet 1: "Summary by User" (Executive KPI banner + table of each user's totals & rates)
      - Sheet 2: "All Detailed Logs" (Comprehensive execution log across all users matching per-run report)
      - Sheet 3..N: Dedicated Tab per User (e.g. "User - Anjali", "User - Kajol jain")
      - Sheet Last: "Event Trace Audit Logs" (Chronological system audit trail)
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
    USER_TAB_FILL = PatternFill(start_color="0F766E", end_color="0F766E", fill_type="solid")  # Teal for user tabs
    LIGHT_GRAY_FILL = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    HEADER_FONT = Font(name=FONT_FAMILY, size=11, bold=True, color="FFFFFF")
    TITLE_FONT = Font(name=FONT_FAMILY, size=13, bold=True, color="FFFFFF")
    BOLD_FONT = Font(name=FONT_FAMILY, size=10, bold=True, color="1E293B")
    REGULAR_FONT = Font(name=FONT_FAMILY, size=10, color="1E293B")
    URL_FONT = Font(name=FONT_FAMILY, size=10, color="2563EB", underline="single")

    # Status badges
    SUCCESS_FILL = PatternFill(start_color="D1FAE5", end_color="D1FAE5", fill_type="solid")
    SUCCESS_FONT = Font(name=FONT_FAMILY, size=10, bold=True, color="065F46")
    FAILED_FILL = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")
    FAILED_FONT = Font(name=FONT_FAMILY, size=10, bold=True, color="991B1B")
    WARN_FILL = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")
    WARN_FONT = Font(name=FONT_FAMILY, size=10, bold=True, color="92400E")

    THIN_BORDER_SIDE = Side(style="thin", color="E2E8F0")
    BORDER_ALL = Border(left=THIN_BORDER_SIDE, right=THIN_BORDER_SIDE, top=THIN_BORDER_SIDE, bottom=THIN_BORDER_SIDE)
    TOP_THICK = Border(top=Side(style="medium", color="1E3A8A"), bottom=Side(style="double", color="1E3A8A"))

    used_sheet_names = []

    # ==========================================
    # SHEET 1: SUMMARY BY USER
    # ==========================================
    ws_users = wb.active
    ws_users.title = "Summary by User"
    used_sheet_names.append("Summary by User")
    ws_users.views.sheetView[0].showGridLines = True

    # 1. Title Banner
    ws_users.merge_cells("A1:K1")
    title_cell = ws_users["A1"]
    title_cell.value = "SEO AUTOMATION - 24-HOUR MULTI-USER PERFORMANCE REPORT"
    title_cell.font = TITLE_FONT
    title_cell.fill = NAVY_FILL
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws_users.row_dimensions[1].height = 36

    # 2. Metadata Subheading
    ws_users.merge_cells("A2:K2")
    sub_cell = ws_users["A2"]
    sub_cell.value = (
        f"Window: {summary['start_time_str']} to {summary['end_time_str']} | "
        f"Active Users: {summary['total_users']} | "
        f"Total Runs: {summary['total_runs']} | "
        f"Overall Success Rate: {summary['overall_success_rate']}%"
    )
    sub_cell.font = Font(name=FONT_FAMILY, size=10, italic=True, color="E2E8F0")
    sub_cell.fill = ACCENT_FILL
    sub_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws_users.row_dimensions[2].height = 24

    ws_users.row_dimensions[3].height = 10

    # 3. Headers
    user_headers = [
        "User Name",
        "Email Address",
        "Total Runs",
        "Success Runs",
        "Failed Runs",
        "Interrupted",
        "Success Rate (%)",
        "First Active (UTC)",
        "Last Active (UTC)",
        "Automations Run",
        "Target Domains / Channels",
    ]
    ws_users.row_dimensions[4].height = 28
    for col_idx, h_text in enumerate(user_headers, start=1):
        c = ws_users.cell(row=4, column=col_idx, value=h_text)
        c.font = HEADER_FONT
        c.fill = NAVY_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = BORDER_ALL

    current_row = 5
    if not users:
        ws_users.merge_cells("A5:K5")
        no_data_cell = ws_users["A5"]
        no_data_cell.value = "No user automation runs recorded in the last 24 hours."
        no_data_cell.font = Font(name=FONT_FAMILY, size=11, italic=True, color="64748B")
        no_data_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws_users.row_dimensions[5].height = 26
        current_row = 6
    else:
        for idx, u in enumerate(users):
            ws_users.row_dimensions[current_row].height = 22
            row_fill = LIGHT_GRAY_FILL if idx % 2 == 1 else PatternFill(fill_type=None)

            c1 = ws_users.cell(row=current_row, column=1, value=u["user_name"])
            c1.font = BOLD_FONT
            c1.alignment = Alignment(horizontal="left", vertical="center")

            c2 = ws_users.cell(row=current_row, column=2, value=u["user_email"])
            c2.font = REGULAR_FONT
            c2.alignment = Alignment(horizontal="left", vertical="center")

            c3 = ws_users.cell(row=current_row, column=3, value=u["total_runs"])
            c3.font = BOLD_FONT
            c3.alignment = Alignment(horizontal="center", vertical="center")

            c4 = ws_users.cell(row=current_row, column=4, value=u["success_runs"])
            c4.font = SUCCESS_FONT if u["success_runs"] > 0 else REGULAR_FONT
            c4.alignment = Alignment(horizontal="center", vertical="center")

            c5 = ws_users.cell(row=current_row, column=5, value=u["failed_runs"])
            c5.font = FAILED_FONT if u["failed_runs"] > 0 else REGULAR_FONT
            c5.alignment = Alignment(horizontal="center", vertical="center")

            c6 = ws_users.cell(row=current_row, column=6, value=u["interrupted_runs"])
            c6.font = WARN_FONT if u["interrupted_runs"] > 0 else REGULAR_FONT
            c6.alignment = Alignment(horizontal="center", vertical="center")

            rate_val = f"{u['success_rate']}%"
            c7 = ws_users.cell(row=current_row, column=7, value=rate_val)
            if u["success_rate"] >= 80.0:
                c7.font = SUCCESS_FONT
                c7.fill = SUCCESS_FILL
            elif u["success_rate"] >= 50.0:
                c7.font = WARN_FONT
                c7.fill = WARN_FILL
            else:
                c7.font = FAILED_FONT
                c7.fill = FAILED_FILL
            c7.alignment = Alignment(horizontal="center", vertical="center")

            c8 = ws_users.cell(row=current_row, column=8, value=_format_dt(u["first_run"]))
            c8.font = REGULAR_FONT
            c8.alignment = Alignment(horizontal="center", vertical="center")

            c9 = ws_users.cell(row=current_row, column=9, value=_format_dt(u["last_run"]))
            c9.font = REGULAR_FONT
            c9.alignment = Alignment(horizontal="center", vertical="center")

            c10 = ws_users.cell(row=current_row, column=10, value=u["automation_types_str"])
            c10.font = REGULAR_FONT
            c10.alignment = Alignment(horizontal="left", vertical="center")

            c11 = ws_users.cell(row=current_row, column=11, value=u["targets_str"])
            c11.font = REGULAR_FONT
            c11.alignment = Alignment(horizontal="left", vertical="center")

            for col_i in range(1, 12):
                cell = ws_users.cell(row=current_row, column=col_i)
                cell.border = BORDER_ALL
                if col_i != 7 and row_fill.fill_type:
                    cell.fill = row_fill

            current_row += 1

        # Summary total row
        ws_users.row_dimensions[current_row].height = 24
        tot_label = ws_users.cell(row=current_row, column=1, value="TOTAL")
        tot_label.font = BOLD_FONT
        tot_label.alignment = Alignment(horizontal="left", vertical="center")

        ws_users.cell(row=current_row, column=2, value="")
        ws_users.cell(row=current_row, column=3, value=summary["total_runs"]).font = BOLD_FONT
        ws_users.cell(row=current_row, column=4, value=summary["total_success"]).font = SUCCESS_FONT
        ws_users.cell(row=current_row, column=5, value=summary["total_failed"]).font = FAILED_FONT
        ws_users.cell(row=current_row, column=6, value=summary["total_interrupted"]).font = WARN_FONT
        ws_users.cell(row=current_row, column=7, value=f"{summary['overall_success_rate']}%").font = BOLD_FONT
        for col_i in range(3, 8):
            ws_users.cell(row=current_row, column=col_i).alignment = Alignment(horizontal="center", vertical="center")
        for col_i in range(1, 12):
            cell = ws_users.cell(row=current_row, column=col_i)
            cell.border = TOP_THICK
            cell.fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")

    # ==========================================
    # SHEET 2: ALL DETAILED LOGS (Match per-run report table)
    # ==========================================
    ws_all_logs = wb.create_sheet(title="All Detailed Logs")
    used_sheet_names.append("All Detailed Logs")
    ws_all_logs.views.sheetView[0].showGridLines = True

    log_columns = [
        "User Name",
        "User Email",
        "Automation Type",
        "Browser",
        "Search Engine",
        "Assigned Engine",
        "Target",
        "Keyword / Query",
        "Status",
        "Result Message / Outcome",
        "Visited URL",
        "Duration",
        "Captcha Encountered",
        "Started At (UTC)",
        "Finished At (UTC)",
        "Run ID",
    ]

    ws_all_logs.row_dimensions[1].height = 28
    for col_idx, h_text in enumerate(log_columns, start=1):
        c = ws_all_logs.cell(row=1, column=col_idx, value=h_text)
        c.font = HEADER_FONT
        c.fill = NAVY_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = BORDER_ALL

    if not runs:
        ws_all_logs.merge_cells("A2:P2")
        no_runs = ws_all_logs["A2"]
        no_runs.value = "No execution runs recorded in the last 24 hours."
        no_runs.font = Font(name=FONT_FAMILY, size=11, italic=True, color="64748B")
        no_runs.alignment = Alignment(horizontal="center", vertical="center")
        ws_all_logs.row_dimensions[2].height = 26
    else:
        for r_idx, r in enumerate(runs, start=2):
            ws_all_logs.row_dimensions[r_idx].height = 20
            row_fill = LIGHT_GRAY_FILL if r_idx % 2 == 1 else PatternFill(fill_type=None)

            c1 = ws_all_logs.cell(row=r_idx, column=1, value=r["user_name"])
            c1.font = BOLD_FONT
            c1.alignment = Alignment(horizontal="left", vertical="center")

            c2 = ws_all_logs.cell(row=r_idx, column=2, value=r["user_email"] or "Not configured")
            c2.font = REGULAR_FONT
            c2.alignment = Alignment(horizontal="left", vertical="center")

            c3 = ws_all_logs.cell(row=r_idx, column=3, value=r["automation_type"])
            c3.font = REGULAR_FONT
            c3.alignment = Alignment(horizontal="center", vertical="center")

            c4 = ws_all_logs.cell(row=r_idx, column=4, value=r["browser"])
            c4.font = REGULAR_FONT
            c4.alignment = Alignment(horizontal="center", vertical="center")

            c5 = ws_all_logs.cell(row=r_idx, column=5, value=r["engine"])
            c5.font = REGULAR_FONT
            c5.alignment = Alignment(horizontal="center", vertical="center")

            c6 = ws_all_logs.cell(row=r_idx, column=6, value=r["assigned_engine"])
            c6.font = REGULAR_FONT
            c6.alignment = Alignment(horizontal="center", vertical="center")

            c7 = ws_all_logs.cell(row=r_idx, column=7, value=r["target"])
            c7.font = REGULAR_FONT
            c7.alignment = Alignment(horizontal="left", vertical="center")

            c8 = ws_all_logs.cell(row=r_idx, column=8, value=r["keyword"])
            c8.font = REGULAR_FONT
            c8.alignment = Alignment(horizontal="left", vertical="center")

            status_str = r["status"]
            c9 = ws_all_logs.cell(row=r_idx, column=9, value=status_str)
            if status_str in ("SUCCESS", "SUBMITTED"):
                c9.font = SUCCESS_FONT
                c9.fill = SUCCESS_FILL
            elif "FAIL" in status_str or "ERR" in status_str:
                c9.font = FAILED_FONT
                c9.fill = FAILED_FILL
            else:
                c9.font = WARN_FONT
                c9.fill = WARN_FILL
            c9.alignment = Alignment(horizontal="center", vertical="center")

            outcome = r.get("outcome_message") or r.get("error_message") or ""
            c10 = ws_all_logs.cell(row=r_idx, column=10, value=outcome)
            c10.font = REGULAR_FONT
            c10.alignment = Alignment(horizontal="left", vertical="center")

            url_val = r.get("visited_url") or ""
            c11 = ws_all_logs.cell(row=r_idx, column=11, value=url_val)
            if url_val and url_val.startswith("http"):
                c11.font = URL_FONT
                try:
                    c11.hyperlink = url_val
                except Exception:
                    pass
            else:
                c11.font = REGULAR_FONT
            c11.alignment = Alignment(horizontal="left", vertical="center")

            c12 = ws_all_logs.cell(row=r_idx, column=12, value=r["duration"])
            c12.font = REGULAR_FONT
            c12.alignment = Alignment(horizontal="center", vertical="center")

            c13 = ws_all_logs.cell(row=r_idx, column=13, value=r["captcha_encountered"])
            c13.font = REGULAR_FONT
            c13.alignment = Alignment(horizontal="center", vertical="center")

            c14 = ws_all_logs.cell(row=r_idx, column=14, value=_format_dt(r["started_at"]))
            c14.font = REGULAR_FONT
            c14.alignment = Alignment(horizontal="center", vertical="center")

            c15 = ws_all_logs.cell(row=r_idx, column=15, value=_format_dt(r["finished_at"]))
            c15.font = REGULAR_FONT
            c15.alignment = Alignment(horizontal="center", vertical="center")

            c16 = ws_all_logs.cell(row=r_idx, column=16, value=r["run_id"])
            c16.font = REGULAR_FONT
            c16.alignment = Alignment(horizontal="left", vertical="center")

            for col_i in range(1, 17):
                cell = ws_all_logs.cell(row=r_idx, column=col_i)
                cell.border = BORDER_ALL
                if col_i != 9 and row_fill.fill_type:
                    cell.fill = row_fill

    # ==========================================
    # SHEET 3..N: DEDICATED TABS FOR EACH USER
    # ==========================================
    user_log_columns = [
        "Browser",
        "Engine",
        "Assigned Engine",
        "Target",
        "Keyword",
        "Status",
        "Result Message / Outcome",
        "Visited URL",
        "Duration",
        "Captcha Encountered",
        "Started At (UTC)",
        "Finished At (UTC)",
        "Automation Type",
        "Run ID",
    ]

    for u in users:
        u_name = u["user_name"]
        sheet_title = _sanitize_sheet_name(f"User - {u_name}", used_sheet_names)
        ws_u = wb.create_sheet(title=sheet_title)
        ws_u.views.sheetView[0].showGridLines = True

        # Header Title for this User
        ws_u.merge_cells("A1:N1")
        u_title = ws_u["A1"]
        u_title.value = (
            f"DETAILED EXECUTION LOGS - USER: {u_name.upper()} "
            f"({u['success_runs']} Success, {u['failed_runs']} Failed | {u['success_rate']}% Success Rate)"
        )
        u_title.font = TITLE_FONT
        u_title.fill = USER_TAB_FILL
        u_title.alignment = Alignment(horizontal="center", vertical="center")
        ws_u.row_dimensions[1].height = 32

        # Subtitle
        ws_u.merge_cells("A2:N2")
        u_sub = ws_u["A2"]
        u_sub.value = (
            f"Email: {u['user_email']} | Total Runs: {u['total_runs']} | "
            f"First Active: {_format_dt(u['first_run'])} | Last Active: {_format_dt(u['last_run'])}"
        )
        u_sub.font = Font(name=FONT_FAMILY, size=10, italic=True, color="E2E8F0")
        u_sub.fill = NAVY_FILL
        u_sub.alignment = Alignment(horizontal="center", vertical="center")
        ws_u.row_dimensions[2].height = 22

        ws_u.row_dimensions[3].height = 8

        # Headers
        ws_u.row_dimensions[4].height = 26
        for col_idx, h_text in enumerate(user_log_columns, start=1):
            c = ws_u.cell(row=4, column=col_idx, value=h_text)
            c.font = HEADER_FONT
            c.fill = NAVY_FILL
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border = BORDER_ALL

        # Data rows for this specific user
        user_runs = u.get("runs", [])
        if not user_runs:
            ws_u.merge_cells("A5:N5")
            no_u_runs = ws_u["A5"]
            no_u_runs.value = "No runs recorded for this user."
            no_u_runs.font = Font(name=FONT_FAMILY, size=11, italic=True, color="64748B")
            no_u_runs.alignment = Alignment(horizontal="center", vertical="center")
            ws_u.row_dimensions[5].height = 24
        else:
            for ur_idx, r in enumerate(user_runs, start=5):
                ws_u.row_dimensions[ur_idx].height = 20
                row_fill = LIGHT_GRAY_FILL if ur_idx % 2 == 1 else PatternFill(fill_type=None)

                c1 = ws_u.cell(row=ur_idx, column=1, value=r["browser"])
                c1.font = REGULAR_FONT
                c1.alignment = Alignment(horizontal="center", vertical="center")

                c2 = ws_u.cell(row=ur_idx, column=2, value=r["engine"])
                c2.font = REGULAR_FONT
                c2.alignment = Alignment(horizontal="center", vertical="center")

                c3 = ws_u.cell(row=ur_idx, column=3, value=r["assigned_engine"])
                c3.font = REGULAR_FONT
                c3.alignment = Alignment(horizontal="center", vertical="center")

                c4 = ws_u.cell(row=ur_idx, column=4, value=r["target"])
                c4.font = REGULAR_FONT
                c4.alignment = Alignment(horizontal="left", vertical="center")

                c5 = ws_u.cell(row=ur_idx, column=5, value=r["keyword"])
                c5.font = REGULAR_FONT
                c5.alignment = Alignment(horizontal="left", vertical="center")

                status_str = r["status"]
                c6 = ws_u.cell(row=ur_idx, column=6, value=status_str)
                if status_str in ("SUCCESS", "SUBMITTED"):
                    c6.font = SUCCESS_FONT
                    c6.fill = SUCCESS_FILL
                elif "FAIL" in status_str or "ERR" in status_str:
                    c6.font = FAILED_FONT
                    c6.fill = FAILED_FILL
                else:
                    c6.font = WARN_FONT
                    c6.fill = WARN_FILL
                c6.alignment = Alignment(horizontal="center", vertical="center")

                outcome = r.get("outcome_message") or r.get("error_message") or ""
                c7 = ws_u.cell(row=ur_idx, column=7, value=outcome)
                c7.font = REGULAR_FONT
                c7.alignment = Alignment(horizontal="left", vertical="center")

                url_val = r.get("visited_url") or ""
                c8 = ws_u.cell(row=ur_idx, column=8, value=url_val)
                if url_val and url_val.startswith("http"):
                    c8.font = URL_FONT
                    try:
                        c8.hyperlink = url_val
                    except Exception:
                        pass
                else:
                    c8.font = REGULAR_FONT
                c8.alignment = Alignment(horizontal="left", vertical="center")

                c9 = ws_u.cell(row=ur_idx, column=9, value=r["duration"])
                c9.font = REGULAR_FONT
                c9.alignment = Alignment(horizontal="center", vertical="center")

                c10 = ws_u.cell(row=ur_idx, column=10, value=r["captcha_encountered"])
                c10.font = REGULAR_FONT
                c10.alignment = Alignment(horizontal="center", vertical="center")

                c11 = ws_u.cell(row=ur_idx, column=11, value=_format_dt(r["started_at"]))
                c11.font = REGULAR_FONT
                c11.alignment = Alignment(horizontal="center", vertical="center")

                c12 = ws_u.cell(row=ur_idx, column=12, value=_format_dt(r["finished_at"]))
                c12.font = REGULAR_FONT
                c12.alignment = Alignment(horizontal="center", vertical="center")

                c13 = ws_u.cell(row=ur_idx, column=13, value=r["automation_type"])
                c13.font = REGULAR_FONT
                c13.alignment = Alignment(horizontal="center", vertical="center")

                c14 = ws_u.cell(row=ur_idx, column=14, value=r["run_id"])
                c14.font = REGULAR_FONT
                c14.alignment = Alignment(horizontal="left", vertical="center")

                for col_i in range(1, 15):
                    cell = ws_u.cell(row=ur_idx, column=col_i)
                    cell.border = BORDER_ALL
                    if col_i != 6 and row_fill.fill_type:
                        cell.fill = row_fill

    # ==========================================
    # SHEET LAST: EVENT TRACE AUDIT LOGS
    # ==========================================
    audit_sheet_title = _sanitize_sheet_name("Event Trace Audit Logs", used_sheet_names)
    ws_trace = wb.create_sheet(title=audit_sheet_title)
    ws_trace.views.sheetView[0].showGridLines = True

    trace_headers = [
        "Timestamp (UTC)",
        "Run ID",
        "User Name",
        "Level",
        "Action",
        "Status",
        "Engine / Site",
        "Keyword",
        "Target / URL",
        "Message",
        "Error Details",
    ]
    ws_trace.row_dimensions[1].height = 28
    for col_idx, h_text in enumerate(trace_headers, start=1):
        c = ws_trace.cell(row=1, column=col_idx, value=h_text)
        c.font = HEADER_FONT
        c.fill = NAVY_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = BORDER_ALL

    if not logs:
        ws_trace.merge_cells("A2:K2")
        no_trace = ws_trace["A2"]
        no_trace.value = "No event logs recorded for the selected runs."
        no_trace.font = Font(name=FONT_FAMILY, size=11, italic=True, color="64748B")
        no_trace.alignment = Alignment(horizontal="center", vertical="center")
        ws_trace.row_dimensions[2].height = 26
    else:
        # Cap audit log rows in Excel to top 10,000 to keep workbook performant and snappy
        max_audit_rows = min(len(logs), 10000)
        for l_idx, log_entry in enumerate(logs[:max_audit_rows], start=2):
            ws_trace.row_dimensions[l_idx].height = 20
            row_fill = LIGHT_GRAY_FILL if l_idx % 2 == 1 else PatternFill(fill_type=None)

            c1 = ws_trace.cell(row=l_idx, column=1, value=_format_dt(log_entry["timestamp"]))
            c1.font = REGULAR_FONT
            c1.alignment = Alignment(horizontal="center", vertical="center")

            c2 = ws_trace.cell(row=l_idx, column=2, value=log_entry["run_id"])
            c2.font = REGULAR_FONT
            c2.alignment = Alignment(horizontal="left", vertical="center")

            c3 = ws_trace.cell(row=l_idx, column=3, value=log_entry["user_name"])
            c3.font = BOLD_FONT
            c3.alignment = Alignment(horizontal="left", vertical="center")

            lvl = log_entry["level"]
            c4 = ws_trace.cell(row=l_idx, column=4, value=lvl)
            if lvl == "ERROR":
                c4.font = FAILED_FONT
                c4.fill = FAILED_FILL
            elif lvl in ("WARNING", "WARN"):
                c4.font = WARN_FONT
                c4.fill = WARN_FILL
            else:
                c4.font = REGULAR_FONT
            c4.alignment = Alignment(horizontal="center", vertical="center")

            c5 = ws_trace.cell(row=l_idx, column=5, value=log_entry["action"])
            c5.font = REGULAR_FONT
            c5.alignment = Alignment(horizontal="left", vertical="center")

            c6 = ws_trace.cell(row=l_idx, column=6, value=log_entry["status"])
            c6.font = REGULAR_FONT
            c6.alignment = Alignment(horizontal="center", vertical="center")

            c7 = ws_trace.cell(row=l_idx, column=7, value=log_entry["engine"])
            c7.font = REGULAR_FONT
            c7.alignment = Alignment(horizontal="center", vertical="center")

            c8 = ws_trace.cell(row=l_idx, column=8, value=log_entry["keyword"])
            c8.font = REGULAR_FONT
            c8.alignment = Alignment(horizontal="left", vertical="center")

            c9 = ws_trace.cell(row=l_idx, column=9, value=log_entry["url"])
            c9.font = REGULAR_FONT
            c9.alignment = Alignment(horizontal="left", vertical="center")

            c10 = ws_trace.cell(row=l_idx, column=10, value=log_entry["message"])
            c10.font = REGULAR_FONT
            c10.alignment = Alignment(horizontal="left", vertical="center")

            c11 = ws_trace.cell(row=l_idx, column=11, value=log_entry["error_message"])
            c11.font = REGULAR_FONT
            c11.alignment = Alignment(horizontal="left", vertical="center")

            for col_i in range(1, 12):
                cell = ws_trace.cell(row=l_idx, column=col_i)
                cell.border = BORDER_ALL
                if col_i != 4 and row_fill.fill_type:
                    cell.fill = row_fill

    # Auto-adjust column widths for all sheets (sampling max 200 rows per sheet for speed)
    for ws in wb.worksheets:
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            # Sample first 200 rows to avoid slow width calculations on large sheets
            for cell in list(col)[:200]:
                if ws == ws_users and cell.row in (1, 2):
                    continue
                if ws.title.startswith("User -") and cell.row in (1, 2):
                    continue
                val_s = str(cell.value or "")
                max_len = max(max_len, len(val_s))
            ws.column_dimensions[col_letter].width = min(max(max_len + 4, 12), 48)

    wb.save(output_file_path)
    logger.info(f"Summary Mailer: Generated 24h summary Excel report at {output_file_path}")
    return str(output_file_path)


def generate_summary_email_html(report_data):
    """
    Renders an executive-grade HTML email template highlighting:
      - 24h overview metrics & KPI cards
      - Active users breakdown table with success/failure badges
      - Notice regarding the downloadable attached Excel file
    """
    summary = report_data["summary"]
    users = report_data["users"]

    def get_rate_color(rate):
        if rate >= 80.0:
            return "#10B981"
        elif rate >= 50.0:
            return "#F59E0B"
        return "#EF4444"

    user_rows_html = ""
    if not users:
        user_rows_html = """
        <tr>
            <td colspan="7" style="text-align:center; padding:20px; color:#64748B; font-style:italic;">
                No automation runs recorded across any users in the last 24 hours.
            </td>
        </tr>
        """
    else:
        for idx, u in enumerate(users):
            bg_color = "#F8FAFC" if idx % 2 == 1 else "#FFFFFF"
            rate_badge_color = get_rate_color(u["success_rate"])
            last_active = _format_dt(u["last_run"]) or "N/A"

            user_rows_html += f"""
            <tr style="background-color: {bg_color}; border-bottom: 1px solid #E2E8F0;">
                <td style="padding: 12px 14px; font-weight: 600; color: #1E293B;">
                    {u['user_name']}
                </td>
                <td style="padding: 12px 14px; color: #475569; font-size: 13px;">
                    {u['user_email']}
                </td>
                <td style="padding: 12px 14px; text-align: center; font-weight: 600; color: #0F172A;">
                    {u['total_runs']}
                </td>
                <td style="padding: 12px 14px; text-align: center; font-weight: 600; color: #10B981;">
                    {u['success_runs']}
                </td>
                <td style="padding: 12px 14px; text-align: center; font-weight: 600; color: #EF4444;">
                    {u['failed_runs']}
                </td>
                <td style="padding: 12px 14px; text-align: center;">
                    <span style="display:inline-block; padding: 4px 10px; border-radius: 9999px; background-color: {rate_badge_color}18; color: {rate_badge_color}; font-weight: 700; font-size: 12px;">
                        {u['success_rate']}%
                    </span>
                </td>
                <td style="padding: 12px 14px; text-align: right; color: #64748B; font-size: 12px;">
                    {last_active}
                </td>
            </tr>
            """

    auto_types_pills = ""
    if summary["automation_type_counts"]:
        for atype, cnt in summary["automation_type_counts"].items():
            auto_types_pills += f"""
            <span style="display:inline-block; margin-right:8px; margin-bottom:6px; padding:4px 12px; background-color:#EFF6FF; border:1px solid #BFDBFE; border-radius:6px; font-size:12px; font-weight:600; color:#1E40AF;">
                {atype}: {cnt} run(s)
            </span>
            """
    else:
        auto_types_pills = "<span style='color:#64748B; font-size:13px;'>No automations recorded</span>"

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

      <table width="700" cellpadding="0" cellspacing="0" style="max-width:700px; width:100%; background-color:#FFFFFF; border-radius:12px; overflow:hidden; box-shadow:0 4px 6px -1px rgba(0, 0, 0, 0.08), 0 2px 4px -1px rgba(0, 0, 0, 0.04); border:1px solid #E2E8F0;">
        
        <!-- HEADER HERO -->
        <tr>
          <td style="background: linear-gradient(135deg, #1E3A8A 0%, #2563EB 100%); padding: 32px 28px; text-align: left; color:#FFFFFF;">
            <div style="font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px; color: #93C5FD; margin-bottom: 6px;">
              Executive Daily Intelligence
            </div>
            <h1 style="margin: 0; font-size: 24px; font-weight: 800; line-height: 1.3; color:#FFFFFF;">
              24-Hour Multi-User Summary Report
            </h1>
            <p style="margin: 8px 0 0; font-size: 14px; color: #DBEAFE; line-height: 1.5;">
              Consolidated performance snapshot across all users from <strong>{summary['start_time_str']}</strong> to <strong>{summary['end_time_str']}</strong>.
            </p>
          </td>
        </tr>

        <!-- MAIN BODY -->
        <tr>
          <td style="padding: 28px;">

            <!-- KPI STAT CARDS -->
            <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 24px;">
              <tr>
                <td width="20%" style="padding: 4px;">
                  <div style="background-color:#F8FAFC; border:1px solid #E2E8F0; border-radius:8px; padding:14px 10px; text-align:center;">
                    <div style="font-size:11px; font-weight:700; text-transform:uppercase; color:#64748B;">Active Users</div>
                    <div style="font-size:22px; font-weight:800; color:#1E293B; margin-top:4px;">{summary['total_users']}</div>
                  </div>
                </td>
                <td width="20%" style="padding: 4px;">
                  <div style="background-color:#F8FAFC; border:1px solid #E2E8F0; border-radius:8px; padding:14px 10px; text-align:center;">
                    <div style="font-size:11px; font-weight:700; text-transform:uppercase; color:#64748B;">Total Runs</div>
                    <div style="font-size:22px; font-weight:800; color:#2563EB; margin-top:4px;">{summary['total_runs']}</div>
                  </div>
                </td>
                <td width="20%" style="padding: 4px;">
                  <div style="background-color:#F8FAFC; border:1px solid #E2E8F0; border-radius:8px; padding:14px 10px; text-align:center;">
                    <div style="font-size:11px; font-weight:700; text-transform:uppercase; color:#64748B;">Success</div>
                    <div style="font-size:22px; font-weight:800; color:#10B981; margin-top:4px;">{summary['total_success']}</div>
                  </div>
                </td>
                <td width="20%" style="padding: 4px;">
                  <div style="background-color:#F8FAFC; border:1px solid #E2E8F0; border-radius:8px; padding:14px 10px; text-align:center;">
                    <div style="font-size:11px; font-weight:700; text-transform:uppercase; color:#64748B;">Failed</div>
                    <div style="font-size:22px; font-weight:800; color:#EF4444; margin-top:4px;">{summary['total_failed']}</div>
                  </div>
                </td>
                <td width="20%" style="padding: 4px;">
                  <div style="background-color:#F8FAFC; border:1px solid #E2E8F0; border-radius:8px; padding:14px 10px; text-align:center;">
                    <div style="font-size:11px; font-weight:700; text-transform:uppercase; color:#64748B;">Success Rate</div>
                    <div style="font-size:22px; font-weight:800; color:{get_rate_color(summary['overall_success_rate'])}; margin-top:4px;">{summary['overall_success_rate']}%</div>
                  </div>
                </td>
              </tr>
            </table>

            <!-- EXCEL ATTACHMENT HIGHLIGHT BOX -->
            <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 24px; background-color: #ECFDF5; border: 1px solid #A7F3D0; border-radius: 8px;">
              <tr>
                <td style="padding: 16px 20px;">
                  <div style="display:flex; align-items:center;">
                    <span style="font-size: 26px; margin-right: 14px;">📊</span>
                    <div>
                      <div style="font-size: 14px; font-weight: 700; color: #065F46;">
                        Detailed User-by-User Execution Logs Attached in Excel (.xlsx)
                      </div>
                      <div style="font-size: 13px; color: #047857; margin-top: 4px; line-height: 1.4;">
                        The attached Excel workbook contains <strong>All Detailed Logs</strong> with full destination URLs, final result messages, keywords, engines, browsers, and durations, plus <strong>Dedicated Tabs for Every User</strong>!
                      </div>
                    </div>
                  </div>
                </td>
              </tr>
            </table>

            <!-- ACTIVE AUTOMATIONS -->
            <div style="margin-bottom: 24px;">
              <div style="font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; color: #475569; margin-bottom: 8px;">
                Automations Executed in Last 24 Hours:
              </div>
              <div>
                {auto_types_pills}
              </div>
            </div>

            <!-- USERS SUMMARY TABLE -->
            <div style="margin-bottom: 12px;">
              <h2 style="margin: 0 0 12px; font-size: 16px; font-weight: 700; color: #0F172A;">
                👥 Active Users Summary
              </h2>
            </div>

            <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; width:100%; font-size:13px; border:1px solid #CBD5E1; border-radius:8px; overflow:hidden;">
              <thead>
                <tr style="background-color: #1E3A8A; color: #FFFFFF;">
                  <th style="padding: 12px 14px; text-align: left; font-weight: 600;">User Name</th>
                  <th style="padding: 12px 14px; text-align: left; font-weight: 600;">Email</th>
                  <th style="padding: 12px 14px; text-align: center; font-weight: 600;">Total Runs</th>
                  <th style="padding: 12px 14px; text-align: center; font-weight: 600;">Success</th>
                  <th style="padding: 12px 14px; text-align: center; font-weight: 600;">Failed</th>
                  <th style="padding: 12px 14px; text-align: center; font-weight: 600;">Success Rate</th>
                  <th style="padding: 12px 14px; text-align: right; font-weight: 600;">Last Active</th>
                </tr>
              </thead>
              <tbody>
                {user_rows_html}
              </tbody>
            </table>

          </td>
        </tr>

        <!-- FOOTER -->
        <tr>
          <td style="background-color: #F8FAFC; border-top: 1px solid #E2E8F0; padding: 20px 28px; text-align: center; color: #64748B; font-size: 12px; line-height: 1.5;">
            <div>
              Automated SEO Reporting Engine &bull; Generated on {summary['end_time_str']}
            </div>
            <div style="margin-top: 4px; color: #94A3B8;">
              Please open the attached Excel file to view the complete detailed logs and dedicated user tabs.
            </div>
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
        "USER BREAKDOWN:",
        "--------------------------------------------------",
    ]

    for u in users:
        lines.append(
            f"* {u['user_name']} ({u['user_email']}): "
            f"{u['total_runs']} runs | {u['success_runs']} success | {u['failed_runs']} failed "
            f"({u['success_rate']}% success) | Last active: {_format_dt(u['last_run'])}"
        )

    lines.extend([
        "",
        "--------------------------------------------------",
        "ATTACHMENT:",
        "The attached Excel file (.xlsx) contains:",
        "1. Summary by User",
        "2. All Detailed Logs (full URLs, browsers, engines, messages, durations)",
        "3. Individual dedicated sheets for every single user",
        "4. Event Trace Audit Logs",
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

    # Load config if not provided
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

    cc_email = cc or email_cfg.get("cc", DEFAULT_ADMIN_CC) or DEFAULT_ADMIN_CC
    cc_email = str(cc_email).strip()

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
        f"[SEO Bot] 24-Hour Multi-User Summary — {summary['total_users']} User(s), "
        f"{summary['total_runs']} Runs ({summary['overall_success_rate']}% Success) — {date_str}"
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
