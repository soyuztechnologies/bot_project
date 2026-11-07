import logging
import smtplib
import time
from email.message import EmailMessage
from pathlib import Path
import os
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

def summary_lines(summary, results, user_name="Unknown", user_email=""):
    by_status = summary.get("byStatus", {})
    status_lines = "\n".join(f"  {status}: {count}" for status, count in by_status.items())
    
    browser_lines = []
    for browser, stats in summary.get("byBrowser", {}).items():
        parts = ", ".join(f"{status}: {count}" for status, count in stats.items() if status != "total")
        browser_lines.append(f"  {browser}: {stats['total']} attempted ({parts})")
    browser_lines_str = "\n".join(browser_lines)
    
    target_lines_list = []
    successful_by_target = {}
    for r in results:
        if r.get("status") in ("success", "submitted"):
            tgt = r.get("target")
            if tgt:
                successful_by_target[tgt] = successful_by_target.get(tgt, 0) + 1

    for url, total_count in summary.get("byTarget", {}).items():
        success_count = successful_by_target.get(url, 0)
        target_lines_list.append(f"  {url}: {success_count} successful")
    
    target_lines = "\n".join(target_lines_list)

    detailed_lines_list = []
    for r in results:
        browser = r.get("browser", "unknown")
        engine = r.get("engine", r.get("site", "unknown"))
        status = r.get("status", "unknown")
        captcha = r.get("captcha_encountered", "False")
        keyword = r.get("keyword", "")
        target = r.get("target", "")
        url = r.get("url", "")
        url_text = f" ({url})" if url else ""
        
        detailed_lines_list.append(f"- [{browser}] [{engine}] [{status}] [Captcha: {captcha}] {keyword} -> {target}{url_text}")
    
    detailed_lines = "\n".join(detailed_lines_list)

    email_display = user_email or summary.get("userEmail") or summary.get("user_email") or "Not configured"
    return f"""User:     {user_name}
Email:    {email_display}
Started:  {summary.get('startedAt', '')}
Finished: {summary.get('finishedAt', '')}
Total attempts: {summary.get('totalAttempts', len(results))}

By status:
{status_lines}

By browser:
{browser_lines_str}

By target link:
{target_lines}

Detailed Session Target Links:
{detailed_lines}"""

def send_report_email(config, summary, results, html_path=None, json_path=None):
    """Send one run report. Returns "sent", "skipped" (disabled / no password) or "failed"."""
    if not isinstance(config, dict):
        config = {}
    email_config = config.get("email", {})
    if not email_config.get("enabled", True):
        logger.info("Report email disabled (email.enabled=false) — skipping.")
        return "skipped"

    # Try loading from .env if not explicitly passed
    load_dotenv()
    # Gmail shows app passwords as "xxxx xxxx xxxx xxxx" — spaces must go.
    app_password = (os.getenv("GMAIL_APP_PASSWORD") or "").strip().replace(" ", "")
    
    if not app_password:
        logger.info("Report email skipped: GMAIL_APP_PASSWORD is not set in environment.")
        return "skipped"

    # Sender / recipients come ONLY from config.json -> "email" (no hardcoded addresses).
    from_email = str(email_config.get("from", "") or "").strip() or "wednesday.ui5@gmail.com"
    to_email = str(email_config.get("to", "") or "").strip()
    configured_to = to_email
    cc_email = str(email_config.get("cc", "") or "").strip()

    # No explicit 'to' -> the first CC address becomes the primary recipient.
    if not to_email:
        cc_list = [a.strip() for a in cc_email.split(",") if a.strip()]
        if cc_list:
            to_email = cc_list[0]
            cc_email = ", ".join(cc_list[1:])

    user_name = (
        summary.get("userName")
        or summary.get("user_name")
        or os.getenv("USER_NAME")
        or (config.get("user_name") if isinstance(config, dict) else None)
        or os.getenv("USERNAME")
        or os.getenv("USER")
        or "Unknown"
    )
    user_name = str(user_name).strip() if user_name else "Unknown"

    raw_user_email = (
        summary.get("userEmail")
        or summary.get("user_email")
        or os.getenv("USER_EMAIL")
        or (config.get("email", {}).get("to") if isinstance(config, dict) and isinstance(config.get("email"), dict) else None)
        or (config.get("user_email") if isinstance(config, dict) else None)
        or configured_to
        or ""
    )
    raw_user_email = str(raw_user_email).strip() if raw_user_email else ""

    # If 'To' is not configured from UI, send to default (anubhav) so email still goes,
    # but in details clearly show 'Not configured' so admins know the user didn't enter an email.
    if raw_user_email:
        to_email = raw_user_email
        user_email_display = raw_user_email
    else:
        to_email = "anubhav.abap@gmail.com"
        user_email_display = "Not configured"

    failed_count = summary.get("byStatus", {}).get("failed", 0) + summary.get("byStatus", {}).get("skipped-captcha", 0)
    interrupted_count = summary.get("byStatus", {}).get("interrupted", 0)

    outcome_parts = []
    if interrupted_count > 0:
        outcome_parts.append(f"{interrupted_count} interrupted")
    if failed_count > 0:
        outcome_parts.append(f"{failed_count} issue(s)")
    outcome = ", ".join(outcome_parts) if outcome_parts else "all clean"

    status_tag = ""
    run_status = str(summary.get("status") or "").upper()
    if "INTERRUPT" in run_status or interrupted_count > 0:
        status_tag = " [INTERRUPTED]"
    elif "FAIL" in run_status or "ERROR" in run_status or failed_count > 0:
        status_tag = " [ISSUES DETECTED]"

    auto_type = summary.get("automationType", "Unknown")
    attempts = summary.get("totalAttempts", len(results))
    finished_time = summary.get("finishedAt") or summary.get("finished_at") or ""
    subject = f"[{auto_type} Automation | User: {user_name}]{status_tag} Rankora Report — {attempts} attempts, {outcome} — {finished_time}"

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = from_email
    msg['To'] = to_email
    if cc_email:
        # Avoid sending CC to the same address as To
        cc_addrs = [a.strip() for a in cc_email.split(",") if a.strip() and a.strip().lower() != to_email.lower()]
        if cc_addrs:
            msg['Cc'] = ", ".join(cc_addrs)
    msg.set_content(summary_lines(summary, results, user_name=user_name, user_email=user_email_display))

    try:
        if html_path and Path(html_path).exists():
            with open(html_path, 'rb') as f:
                html_data = f.read()
                msg.add_attachment(html_data, maintype='text', subtype='html', filename='report.html')
            
        if json_path and Path(json_path).exists():
            with open(json_path, 'rb') as f:
                json_data = f.read()
                msg.add_attachment(json_data, maintype='application', subtype='json', filename='report.json')

    except Exception as e:
        logger.error(f"Failed to attach report files (sending without them): {e}")

    # Parallel runs (website + youtube + backlink) can all finish at once and a
    # network blip must not lose a report, so transient SMTP errors are retried.
    max_tries = 3
    for attempt in range(1, max_tries + 1):
        try:
            with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=30) as smtp:
                try:
                    smtp.login(from_email, app_password)
                except smtplib.SMTPServerDisconnected as e:
                    # Gmail closes the connection instead of a clean 535 when the
                    # app password is wrong/revoked — tell the user exactly that.
                    raise smtplib.SMTPAuthenticationError(
                        535,
                        b"Login rejected: Gmail closed the connection. "
                        b"Regenerate an App Password (Google Account > 2-Step Verification > App passwords) "
                        b"and update GMAIL_APP_PASSWORD in .env / GitHub Secrets.",
                    ) from e
                smtp.send_message(msg)
            logger.info(f"Report email (User: {user_name}, Email: {user_email_display}) sent successfully to {to_email} (CC: {cc_email})")
            return "sent"
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"Failed to send report email (authentication, not retrying): {e}")
            return "failed"
        except Exception as e:
            if attempt < max_tries:
                logger.warning(f"Report email attempt {attempt}/{max_tries} failed: {e} — retrying")
                time.sleep(5 * attempt)
            else:
                logger.error(f"Failed to send report email after {max_tries} attempts: {e}")
    return "failed"


# Re-export 24-hour summary mailer flow
try:
    from utils.summary_mailer import (
        send_24h_summary_report,
        fetch_24h_summary_data,
        create_summary_excel_report,
    )
except ImportError:
    pass
