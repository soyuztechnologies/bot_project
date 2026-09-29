import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path
import os
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

def summary_lines(summary, results):
    status_lines = "\n".join(f"  {status}: {count}" for status, count in summary["byStatus"].items())
    
    browser_lines = []
    for browser, stats in summary["byBrowser"].items():
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

    for url, total_count in summary["byTarget"].items():
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

    return f"""Started:  {summary['startedAt']}
Finished: {summary['finishedAt']}
Total attempts: {summary['totalAttempts']}

By status:
{status_lines}

By browser:
{browser_lines_str}

By target link:
{target_lines}

Detailed Session Target Links:
{detailed_lines}"""

def send_report_email(config, summary, results, html_path, json_path):
    email_config = config.get("email", {})
    if not email_config.get("enabled", False):
        logger.info("Report email disabled (email.enabled=false) — skipping.")
        return

    # Try loading from .env if not explicitly passed
    load_dotenv()
    app_password = os.getenv("GMAIL_APP_PASSWORD")
    
    if not app_password:
        logger.info("Report email skipped: GMAIL_APP_PASSWORD is not set in environment.")
        return

    from_email = email_config.get("from", "your_email@gmail.com")
    to_email = email_config.get("to", "recipient@gmail.com")
    
    failed_count = summary["byStatus"].get("failed", 0) + summary["byStatus"].get("skipped-captcha", 0)
    outcome = f"{failed_count} issue(s)" if failed_count > 0 else "all clean"
    auto_type = summary.get("automationType", "Unknown")
    subject = f"[{auto_type} Automation] SEO Report — {summary['totalAttempts']} attempts, {outcome} — {summary['finishedAt']}"

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = from_email
    msg['To'] = to_email
    msg.set_content(summary_lines(summary, results))

    try:
        with open(html_path, 'rb') as f:
            html_data = f.read()
            msg.add_attachment(html_data, maintype='text', subtype='html', filename='report.html')
            
        with open(json_path, 'rb') as f:
            json_data = f.read()
            msg.add_attachment(json_data, maintype='application', subtype='json', filename='report.json')

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(from_email, app_password)
            smtp.send_message(msg)
            
        logger.info(f"Report email sent successfully to {to_email}")
    except Exception as e:
        logger.error(f"Failed to send report email: {e}")
