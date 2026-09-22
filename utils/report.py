import json
import os
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

STATUS_COLORS = {
    "success": "#1a7f37",
    "submitted": "#1a7f37",
    "failed": "#c1121f",
    "interrupted": "#b8860b",
    "skipped-captcha": "#b8860b",
    "skipped-protected": "#b8860b",
}

def escape_html(text):
    if not text:
        return ""
    text = str(text)
    html_escape_table = {
        "&": "&amp;",
        '"': "&quot;",
        "'": "&apos;",
        ">": "&gt;",
        "<": "&lt;",
    }
    return "".join(html_escape_table.get(c, c) for c in text)

class RunLogger:
    def __init__(self, logs_dir="logs", target_urls=None, started_at=None, automation_type="Unknown"):
        if started_at:
            self.started_at = started_at
        else:
            self.started_at = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
        
        self.automation_type = automation_type
        
        # Resolve path relative to project root
        base_dir = Path(__file__).resolve().parent.parent
        self.logs_dir = base_dir / logs_dir
        
        self.target_urls = target_urls or []
        self.results = []
        
        if not self.logs_dir.exists():
            self.logs_dir.mkdir(parents=True, exist_ok=True)
            
        stamp = self.started_at.strftime("%Y-%m-%dT%H-%M-%S")
        self.json_path = self.logs_dir / f"run-{stamp}.json"
        self.html_path = self.logs_dir / f"run-{stamp}.html"

    def set_results_from_stats(self, stats, config=None):
        """
        Converts the python 'stats' dict from workflows into a generic results list.
        stats format: {"success": [{...}], "failed": [{...}], "interrupted": [{...}]}
        """
        self.results = []
        global_browser = config.get("browser", {}).get("name", "unknown") if config else "unknown"
        default_target = self.target_urls[0] if self.target_urls else ""
        
        for status in ["success", "failed", "interrupted"]:
            for item in stats.get(status, []):
                # Generic fallback for missing fields based on how python workflows structure them
                dur_ms = item.get("durationMs")
                duration_str = ""
                if dur_ms is not None:
                    total_seconds = int(dur_ms / 1000)
                    mins = total_seconds // 60
                    secs = total_seconds % 60
                    if mins > 0:
                        duration_str = f"{mins}m {secs}s"
                    else:
                        duration_str = f"{secs}s"

                entry = {
                    "browser": item.get("browser", global_browser),
                    "target": item.get("target", item.get("target_url", default_target)),
                    "keyword": item.get("keyword", ""),
                    "status": status,
                    "message": item.get("message", item.get("error", "")),
                    "duration": duration_str,
                    "captcha_encountered": str(item.get("captcha_encountered", "False")),
                    "automation_type": self.automation_type
                }
                
                if self.automation_type in ["Web", "YouTube", "Web & YouTube"]:
                    entry["engine"] = item.get("site", item.get("engine", "unknown"))
                else:
                    entry["site"] = item.get("site", item.get("engine", "unknown"))
                
                entry["url"] = item.get("url", "")
                self.results.append(entry)

    def summary(self):
        by_status = {}
        for r in self.results:
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1
            
        by_browser = {}
        for r in self.results:
            b = r["browser"]
            if b not in by_browser:
                by_browser[b] = {"total": 0}
            by_browser[b]["total"] += 1
            by_browser[b][r["status"]] = by_browser[b].get(r["status"], 0) + 1
            
        by_target = {}
        for r in self.results:
            if not r.get("target"):
                continue
            by_target[r["target"]] = by_target.get(r["target"], 0) + 1

        finished_at = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
        return {
            "startedAt": self.started_at.strftime("%d %b %Y, %I:%M:%S %p IST"),
            "finishedAt": finished_at.strftime("%d %b %Y, %I:%M:%S %p IST"),
            "targetUrls": self.target_urls,
            "totalAttempts": len(self.results),
            "byStatus": by_status,
            "byBrowser": by_browser,
            "byTarget": by_target,
            "automationType": self.automation_type,
        }

    def write_json(self):
        payload = {
            "summary": self.summary(),
            "results": self.results
        }
        with open(self.json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        return str(self.json_path)

    def write_html(self):
        summary = self.summary()
        auto_type = summary.get("automationType", "Unknown")
        is_web_yt = auto_type in ["Web", "YouTube", "Web & YouTube"]
        
        rows = ""
        for r in self.results:
            duration = escape_html(r.get("duration", ""))
            target_link = f"<a href=\"{escape_html(r['target'])}\" target=\"_blank\">{escape_html(r['target'])}</a>" if r.get("target") else ""
            color = STATUS_COLORS.get(r["status"], "#555")
            
            if is_web_yt:
                rows += f'''
            <tr>
                <td>{escape_html(r.get('browser', ''))}</td>
                <td>{escape_html(r.get('engine', ''))}</td>
                <td>{target_link}</td>
                <td>{escape_html(r.get('keyword', ''))}</td>
                <td style="color:{color};font-weight:600">{escape_html(r['status'])}</td>
                <td>{escape_html(r.get('message', ''))}</td>
                <td>{duration}</td>
                <td>{escape_html(r.get('captcha_encountered', ''))}</td>
                <td>{escape_html(r.get('automation_type', ''))}</td>
            </tr>'''
            else:
                rows += f'''
            <tr>
                <td>{escape_html(r.get('browser', ''))}</td>
                <td>{escape_html(r.get('site', ''))}</td>
                <td><a href="{escape_html(r.get('url', ''))}" target="_blank">{escape_html(r.get('url', ''))}</a></td>
                <td>{target_link}</td>
                <td>{escape_html(r.get('keyword', ''))}</td>
                <td style="color:{color};font-weight:600">{escape_html(r['status'])}</td>
                <td>{escape_html(r.get('message', ''))}</td>
                <td>{duration}</td>
                <td>{escape_html(r.get('captcha_encountered', ''))}</td>
            </tr>'''

        status_rows = "".join(f'<li><span style="color:{STATUS_COLORS.get(status, "#555")};font-weight:600">{escape_html(status)}</span>: {count}</li>' for status, count in summary["byStatus"].items())
        
        browser_rows = ""
        for browser, stats in summary["byBrowser"].items():
            parts = ", ".join(f"{escape_html(status)}: {count}" for status, count in stats.items() if status != "total")
            browser_rows += f"<li><strong>{escape_html(browser)}</strong> &mdash; {stats['total']} attempted ({parts})</li>"
            
        target_breakdown_rows = "".join(f'<li><a href="{escape_html(url)}">{escape_html(url)}</a> &mdash; {count}</li>' for url, count in summary["byTarget"].items())

        table_headers = "<tr><th>Browser</th><th>Engine</th><th>Target</th><th>Keyword</th><th>Status</th><th>Message</th><th>Duration</th><th>Captcha Encountered</th><th>Automation Type</th></tr>" if is_web_yt else "<tr><th>Browser</th><th>Site</th><th>URL</th><th>Target</th><th>Keyword</th><th>Status</th><th>Message</th><th>Duration</th><th>Captcha Encountered</th></tr>"

        html = f'''<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{auto_type} SEO Automation Report</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Arial, sans-serif; margin: 24px; color: #1c1c1c; background: #fafafa; }}
  h1 {{ font-size: 20px; }}
  h2 {{ font-size: 16px; margin-top: 28px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; background: #fff; }}
  th, td {{ border: 1px solid #ddd; padding: 6px 8px; text-align: left; vertical-align: top; }}
  th {{ background: #f0f0f0; }}
  ul {{ padding-left: 20px; }}
  .meta {{ color: #555; font-size: 13px; }}
</style>
</head>
<body>
  <h1>{auto_type} SEO Automation Report</h1>
  <p class="meta">
    Started: {escape_html(summary['startedAt'])}<br>
    Finished: {escape_html(summary['finishedAt'])}<br>
    Total attempts: {summary['totalAttempts']}
  </p>

  <h2>Summary by status</h2>
  <ul>{status_rows}</ul>

  <h2>Summary by browser</h2>
  <ul>{browser_rows}</ul>

  <h2>By target link</h2>
  <ul>{target_breakdown_rows}</ul>

  <h2>Full log</h2>
  <table>
    <thead>
      {table_headers}
    </thead>
    <tbody>{rows}</tbody>
  </table>
</body>
</html>'''

        with open(self.html_path, "w", encoding="utf-8") as f:
            f.write(html)
        return str(self.html_path)
