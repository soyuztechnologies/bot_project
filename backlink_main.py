"""
backlink_main.py

Entry point for "Generate Backlinks" (ping submission) automation.

Flow:
  Load config -> load 5 ping sites -> load Anubhav targets ->
  read sites one by one -> open `sessions.parallel` (5) browsers per batch ->
  submit first 5 targets, next 5, ... (different link per browser) ->
  wait for each site to finish -> logs to DB (automation_type BACKLINK) ->
  close sessions -> continue next batch / next site.

Usage:
  python backlink_main.py                  # full run (all enabled sites x all targets)
  python backlink_main.py --dry-run        # validate config + DB, no browser
  python backlink_main.py --sites pingmyurls,pingmylinks
  python backlink_main.py --max-targets 5  # smoke test: first N targets only
  python backlink_main.py --list           # show sites + targets and exit
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from automation.backlink.backlink_session import start_parallel_backlink_sessions
from utils.database import check_db_connection, close_connection_pool, initialize_database, DatabaseHandler
from utils.exceptions import ConfigError, ConfigFileNotFoundError, ConfigInvalidError, ValidationError, wrap_unexpected
from utils.logger import setup_logger
# from utils.vpn_manager import connect_vpn, disconnect_vpn  # VPN DISABLED - commented out

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent


def load_json(path):
    path = Path(path)
    if not path.exists():
        raise ConfigFileNotFoundError(f"Required file not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigInvalidError(f"Invalid JSON in {path}: {e}", cause=e) from e
    except OSError as e:
        raise ConfigError(f"Failed to read {path}: {e}", cause=e) from e
    except Exception as e:
        raise wrap_unexpected(e, f"load_json {path}") from e


def resolve_backlink_files(config):
    bl = config.get("backlink", {}) or {}
    files = config.get("files", {}) or {}
    sites_rel = bl.get("sitesFile") or files.get("backlinkSites") or "data/backlink_sites.json"
    targets_rel = bl.get("targetsFile") or files.get("backlinkTargets") or "data/backlink_targets.json"
    return BASE_DIR / sites_rel, BASE_DIR / targets_rel


def validate_backlink_inputs(config, sites, targets):
    if "sessions" not in config or "browser" not in config:
        raise ValidationError("config.json must contain 'browser' and 'sessions' sections.")
    try:
        parallel = int(config["sessions"].get("parallel", 1))
    except (TypeError, ValueError) as e:
        raise ValidationError(f"sessions.parallel must be integer: {e}", cause=e) from e
    if parallel < 1:
        raise ValidationError("sessions.parallel must be 1 or greater.")
    if not isinstance(sites, list) or not sites:
        raise ValidationError("data/backlink_sites.json must contain at least one site.")
    enabled = [s for s in sites if s.get("enabled", True)]
    if not enabled:
        raise ValidationError("No enabled backlink sites (all have enabled=false).")
    for s in enabled:
        if not s.get("id") or not s.get("url"):
            raise ValidationError(f"Backlink site missing id/url: {s}")
    if not isinstance(targets, list) or not targets:
        raise ValidationError("data/backlink_targets.json must contain at least one target.")
    for t in targets:
        if not t.get("url"):
            raise ValidationError(f"Backlink target missing url: {t}")
    return enabled, parallel


def print_summary(stats):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ok = stats.get("success", [])
    fail = stats.get("failed", [])
    intr = stats.get("interrupted", [])
    try:
        ok = sorted(ok, key=lambda x: str(x.get("keyword", "")))
        fail = sorted(fail, key=lambda x: str(x.get("keyword", "")))
        intr = sorted(intr, key=lambda x: str(x.get("keyword", "")))
    except Exception:
        pass
    print(f"{ts} - INFO - " + "=" * 50, flush=True)
    print(f"{ts} - INFO - " + " Backlink Session Summary ".center(50, "="), flush=True)
    for s in ok:
        try:
            print(f"✓ {str(s.get('keyword',''))[:36]:<38} [{s.get('engine','')}]", flush=True)
        except UnicodeEncodeError:
            print(f"[OK] {str(s.get('keyword',''))[:36]:<38} [{s.get('engine','')}]", flush=True)
    if ok and fail:
        print(flush=True)
    for s in fail:
        try:
            print(f"✗ {str(s.get('keyword',''))[:36]:<38} [{s.get('engine','')}]", flush=True)
        except UnicodeEncodeError:
            print(f"[FAIL] {str(s.get('keyword',''))[:36]:<38} [{s.get('engine','')}]", flush=True)
    if fail and intr:
        print(flush=True)
    for s in intr:
        try:
            print(f"[INT] {str(s.get('keyword',''))[:36]:<38} [{s.get('engine','')}]", flush=True)
        except UnicodeEncodeError:
            print(f"[INT] {str(s.get('keyword',''))[:36]:<38} [{s.get('engine','')}]", flush=True)
    print(f"{ts} - INFO - " + "-" * 50, flush=True)
    print(f"{ts} - INFO - Total   : {stats.get('total', len(ok) + len(fail) + len(intr))}", flush=True)
    print(f"{ts} - INFO - Success : {len(ok)}", flush=True)
    print(f"{ts} - INFO - Failed  : {len(fail)}", flush=True)
    print(f"{ts} - INFO - Interrupted : {len(intr)}", flush=True)
    print(f"{ts} - INFO - " + "=" * 50, flush=True)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Generate Backlinks (ping) automation")
    p.add_argument("--sites", default="", help="Comma-separated site ids to run (default: all enabled). E.g. --sites pingmyurls,pingmylinks")
    p.add_argument("--max-targets", type=int, default=0, help="Only use first N targets (smoke test). 0 = all.")
    p.add_argument("--dry-run", action="store_true", help="Validate config + DB only, do not open browsers.")
    p.add_argument("--list", action="store_true", help="List sites + targets and exit.")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    start_time = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    stats = None
    config = None
    targets = []
    # vpn_connected = False  # VPN DISABLED - commented out
    try:
        setup_logger()
        logging.getLogger().addHandler(DatabaseHandler())
        initialize_database()
        check_db_connection()
        logger.info("=" * 50)
        logger.info("Generate Backlinks Started")
        logger.info("=" * 50)

        config = load_json(BASE_DIR / "config.json")
        sites_path, targets_path = resolve_backlink_files(config)
        sites = load_json(sites_path)
        targets = load_json(targets_path)

        enabled, parallel = validate_backlink_inputs(config, sites, targets)

        if args.sites.strip():
            wanted = {s.strip().lower() for s in args.sites.split(",") if s.strip()}
            enabled = [s for s in enabled if str(s.get("id", "")).lower() in wanted]
            if not enabled:
                raise ValidationError(f"--sites matched nothing. Available: {[s.get('id') for s in sites]}")

        if args.max_targets and args.max_targets > 0:
            targets = targets[: args.max_targets]

        logger.info(f"Project Path      : {BASE_DIR}")
        logger.info(f"Backlink Sites    : {', '.join(s.get('id') for s in enabled)}")
        logger.info(f"Targets           : {len(targets)}")
        logger.info(f"Parallel Sessions : {parallel} (batches of {parallel})")
        logger.info(f"Planned Jobs      : {len(enabled) * len(targets)}")

        if args.list:
            print("\nBacklink sites:")
            for s in enabled:
                print(f"  - {s.get('id'):<15} {s.get('url')}")
            print(f"\nTargets ({len(targets)}):")
            for t in targets:
                print(f"  - [{t.get('category','')}] {t.get('url')}  (keyword: {t.get('keyword','')})")
            return {"total": 0, "success": [], "failed": [], "interrupted": []}

        if args.dry_run:
            logger.info("Dry-run: config + DB OK, browsers not started.")
            print(f"\nDry-run OK: {len(enabled)} site(s) x {len(targets)} target(s) = {len(enabled)*len(targets)} jobs. DB reachable check done above.")
            return {"total": len(enabled) * len(targets), "success": [], "failed": [], "interrupted": []}

        # vpn_config = config.get("vpn", {})  # VPN DISABLED - commented out
        # if vpn_config.get("enabled", False):  # VPN DISABLED - commented out
        #     logger.info("Connecting to VPN before backlink automation.")  # VPN DISABLED - commented out
        #     #connect_vpn()  # VPN DISABLED - commented out
        #     vpn_connected = True  # VPN DISABLED - commented out
        #     logger.info("VPN connected and verified.")  # VPN DISABLED - commented out

        stats = start_parallel_backlink_sessions(enabled, targets, config)
        return stats

    except KeyboardInterrupt:
        logger.info("Backlink automation stopped by user (Ctrl+C).")
        return stats
    except (ConfigError, ValidationError) as e:
        logger.error(f"Configuration error: {e} [{type(e).__name__}]", exc_info=False)
        print(f"\nConfiguration error: {e}")
        return stats
    except Exception as e:
        wrapped = e if isinstance(e, Exception) else wrap_unexpected(e, "backlink_main")
        logger.error(f"Backlink automation error: {wrapped}", exc_info=True)
        print(f"\nBacklink automation error: {wrapped}")
        return stats
    finally:
        if stats is not None and not args.list and not args.dry_run:
            try:
                print_summary(stats)
            except Exception as e:
                logger.error(f"Failed to print backlink summary: {e}", exc_info=True)
            try:
                from utils.report import RunLogger
                from utils.mailer import send_report_email
                target_urls = [t.get("url") for t in targets] if targets else []
                reporter = RunLogger(target_urls=target_urls, started_at=start_time, automation_type="Backlink")
                reporter.set_results_from_stats(stats, config)
                json_path = reporter.write_json()
                html_path = reporter.write_html()
                if config:
                    send_report_email(config, reporter.summary(), html_path, json_path)
            except Exception as e:
                logger.error(f"Failed to generate report or send email: {e}", exc_info=True)
        # if vpn_connected:  # VPN DISABLED - commented out
        #     try:  # VPN DISABLED - commented out
        #         logger.info("Disconnecting VPN after backlink automation.")  # VPN DISABLED - commented out
        #         #disconnect_vpn()  # VPN DISABLED - commented out
        #     except Exception as e:  # VPN DISABLED - commented out
        #         logger.error(f"Failed to disconnect VPN: {e}", exc_info=True)  # VPN DISABLED - commented out
        try:
            close_connection_pool()
        except Exception:
            pass
        logger.info("Generate Backlinks Finished.")


if __name__ == "__main__":
    main()
