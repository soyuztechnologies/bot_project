#!/usr/bin/env python3
"""
send_summary_report.py

CLI entry point to generate and send a 24-hour multi-user summary report email
with a downloadable Excel spreadsheet (.xlsx) attachment containing all user runs
and detailed execution logs.

Usage:
    python send_summary_report.py
    python send_summary_report.py --hours 24
    python send_summary_report.py --to myemail@example.com
    python send_summary_report.py --dry-run
"""

import sys
import argparse
import logging
from utils.summary_mailer import send_24h_summary_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("send_summary_report")


def main():
    parser = argparse.ArgumentParser(
        description="Send 24-Hour Multi-User Summary Report with Excel attachment."
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Number of hours in the lookback window (default: 24).",
    )
    parser.add_argument(
        "--to",
        type=str,
        default=None,
        help="Recipient email address (defaults to configured email or admin).",
    )
    parser.add_argument(
        "--cc",
        type=str,
        default=None,
        help="CC recipients comma-separated (defaults to standard admin CCs).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate Excel and log summary without actually dispatching email.",
    )
    parser.add_argument(
        "--save-dir",
        type=str,
        default="logs",
        help="Directory where generated Excel file is stored (default: logs).",
    )

    args = parser.parse_args()

    print("======================================================================")
    print(f"  RANKORA - 24-HOUR MULTI-USER SUMMARY REPORT GENERATOR")
    print("======================================================================")
    print(f"  Window:      Past {args.hours} hours")
    if args.to:
        print(f"  Recipient:   {args.to}")
    if args.dry_run:
        print(f"  Mode:        DRY RUN (no email will be sent)")
    print("----------------------------------------------------------------------")

    result = send_24h_summary_report(
        hours=args.hours,
        recipient=args.to,
        cc=args.cc,
        save_dir=args.save_dir,
        dry_run=args.dry_run,
    )

    if result.get("success"):
        summary = result.get("summary", {})
        print("\n[+] SUCCESS! Summary Report Processed:")
        print(f"    - Active Users:    {summary.get('total_users', 0)}")
        print(f"    - Total Runs:      {summary.get('total_runs', 0)}")
        print(f"    - Successful:      {summary.get('total_success', 0)}")
        print(f"    - Failed:          {summary.get('total_failed', 0)}")
        print(f"    - Success Rate:    {summary.get('overall_success_rate', 0.0)}%")
        print(f"    - Excel File:      {result.get('excel_path')}")
        if result.get("dry_run"):
            print(f"    - Email Target:    {result.get('to')} (Dry Run - Not Sent)")
        else:
            print(f"    - Email Sent To:   {result.get('to')} (CC: {result.get('cc')})")
        print("======================================================================\n")
        return 0
    else:
        print(f"\n[-] ERROR: Failed to generate/send report: {result.get('error')}")
        if result.get("excel_path"):
            print(f"    - Generated Excel is preserved at: {result.get('excel_path')}")
        print("======================================================================\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())

