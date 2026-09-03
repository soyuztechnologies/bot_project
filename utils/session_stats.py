"""
session_stats.py
 
Collect automation statistics and print
a summary after all sessions complete.
"""
 
 
class SessionStats:
 
    def __init__(self):
 
        # --------------------------------
        # Session Statistics
        # --------------------------------
 
        self.total_sessions = 0
        self.successful_sessions = 0
        self.failed_sessions = 0
 
        # --------------------------------
        # Keyword Statistics
        # --------------------------------
 
        self.total_keywords = 0
        self.keywords_processed = 0
        self.keywords_failed = 0
 
        # --------------------------------
        # Video Statistics
        # --------------------------------
 
        self.videos_found = 0
        self.videos_not_found = 0
 
        # --------------------------------
        # Watch Statistics
        # --------------------------------
 
        self.total_watch_time = 0
 
        # --------------------------------
        # Browser Statistics
        # --------------------------------
 
        self.browser_usage = {}
 
        # --------------------------------
        # Per-keyword Records
        # --------------------------------
 
        self.success = []
        self.failed = []
 
        # --------------------------------
        # Error / Retry Statistics
        # --------------------------------
 
        self.retry_count = 0
        self.browser_errors = 0
        self.search_errors = 0
 
    # ==================================
    # DICT-STYLE ACCESS
    # ==================================
 
    def __getitem__(self, key):
 
        if key == "success":
            return self.success
 
        if key == "failed":
            return self.failed
 
        if key == "total":
            return (
                self.successful_sessions
                + self.failed_sessions
            )
 
        raise KeyError(key)
 
    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default
 
    def record_keyword_success(self, keyword, engine="unknown"):
        """Record per-keyword success for tick/cross summary (like main.py)."""
        try:
            self.success.append({"keyword": str(keyword), "engine": str(engine)})
        except Exception:
            pass
 
    def record_keyword_failed(self, keyword, engine="unknown"):
        """Record per-keyword failure for tick/cross summary."""
        try:
            self.failed.append({"keyword": str(keyword), "engine": str(engine)})
        except Exception:
            pass
 
    # ==================================
    # SESSION METHODS
    # ==================================
 
    def record_browser(self, browser):
 
        self.total_sessions += 1
 
        self.browser_usage[browser] = (
            self.browser_usage.get(browser, 0) + 1
        )
 
    def record_success(self):
 
        self.successful_sessions += 1
 
    def record_failure(self):
 
        self.failed_sessions += 1
 
    # ==================================
    # KEYWORD METHODS
    # ==================================
 
    def record_keyword(self):
 
        self.keywords_processed += 1
 
    def record_keyword_failure(self):
 
        self.keywords_failed += 1
 
    # ==================================
    # VIDEO METHODS
    # ==================================
 
    def record_video_found(self):
 
        self.videos_found += 1
 
    def record_video_not_found(self):
 
        self.videos_not_found += 1
 
    # ==================================
    # WATCH TIME
    # ==================================
 
    def record_watch_time(self, seconds):
 
        if seconds is None:
            return
 
        try:
            self.total_watch_time += int(seconds)
 
        except (TypeError, ValueError):
 
            pass
 
    # ==================================
    # RETRY
    # ==================================
 
    def record_retry(self):
 
        self.retry_count += 1
 
    # ==================================
    # ERROR METHODS
    # ==================================
 
    def record_browser_error(self):
 
        self.browser_errors += 1
 
    def record_search_error(self):
 
        self.search_errors += 1
 
    # ==================================
    # SUMMARY
    # ==================================
 
    def print_summary(self):
 
        import logging
        logger = logging.getLogger(__name__)
        # Main.py-style per-keyword tick/cross header (even on Ctrl+C/error) - use print for all to keep order, mimic logger timestamp
        try:
            import sys
            from datetime import datetime
            try:
                sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            except Exception:
                pass
            success_sorted = sorted(self.success, key=lambda x: str(x.get("keyword", "")))
            failed_sorted = sorted(self.failed, key=lambda x: str(x.get("keyword", "")))
            if success_sorted or failed_sorted:
                # Use print with logger-like timestamp to keep order with tick prints (all via print)
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"{ts} - INFO - " + "=" * 60, flush=True)
                print(f"{ts} - INFO - " + " Session Summary ".center(60, "="), flush=True)
                for s in success_sorted:
                    try:
                        print(f"✓ {str(s.get('keyword','')):<30} [{str(s.get('engine',''))}]", flush=True)
                    except UnicodeEncodeError:
                        print(f"[OK] {str(s.get('keyword','')):<30} [{str(s.get('engine',''))}]", flush=True)
                if success_sorted and failed_sorted:
                    print(flush=True)
                for f in failed_sorted:
                    try:
                        print(f"✗ {str(f.get('keyword','')):<30} [{str(f.get('engine',''))}]", flush=True)
                    except UnicodeEncodeError:
                        print(f"[FAIL] {str(f.get('keyword','')):<30} [{str(f.get('engine',''))}]", flush=True)
                print(f"{ts} - INFO - " + "-" * 60, flush=True)
                try:
                    total = len(success_sorted) + len(failed_sorted)
                    print(f"{ts} - INFO - Total   : {total}", flush=True)
                    print(f"{ts} - INFO - Success : {len(success_sorted)}", flush=True)
                    print(f"{ts} - INFO - Failed  : {len(failed_sorted)}", flush=True)
                except Exception:
                    pass
                print(f"{ts} - INFO - " + "=" * 60, flush=True)
        except Exception:
            pass
 
        print("\n")
        print("=" * 60)
        print("              AUTOMATION SUMMARY")
        print("=" * 60)
 
        # --------------------------------
        # Sessions
        # --------------------------------
 
        print(
            f"Sessions Started     : "
            f"{self.total_sessions}"
        )
 
        print(
            f"Successful Sessions  : "
            f"{self.successful_sessions}"
        )
 
        print(
            f"Failed Sessions      : "
            f"{self.failed_sessions}"
        )
 
        # --------------------------------
        # Browser Usage
        # --------------------------------
 
        print("\nBrowser Usage")
 
        if self.browser_usage:
 
            for browser, count in self.browser_usage.items():
 
                print(
                    f"  {browser:<10}: "
                    f"{count}"
                )
 
        else:
 
            print("  None")
 
        # --------------------------------
        # Keywords
        # --------------------------------
 
        print("\nKeywords")
 
        print(
            f"  Processed          : "
            f"{self.keywords_processed}"
        )
 
        print(
            f"  Failed             : "
            f"{self.keywords_failed}"
        )
 
        # --------------------------------
        # Videos
        # --------------------------------
 
        print("\nVideos")
 
        print(
            f"  Found              : "
            f"{self.videos_found}"
        )
 
        print(
            f"  Not Found          : "
            f"{self.videos_not_found}"
        )
 
        # --------------------------------
        # Watch Time
        # --------------------------------
 
        print("\nWatch Time")
 
        print(
            f"  Total              : "
            f"{self.total_watch_time} sec"
        )
 
        # --------------------------------
        # Errors
        # --------------------------------
 
        print("\nErrors")
 
        print(
            f"  Browser Errors     : "
            f"{self.browser_errors}"
        )
 
        print(
            f"  Search Errors      : "
            f"{self.search_errors}"
        )
 
        # --------------------------------
        # Retries
        # --------------------------------
 
        print("\nRetries")
 
        print(
            f"  Retry Count        : "
            f"{self.retry_count}"
        )
 
        print("=" * 60)