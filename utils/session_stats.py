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
        self.interrupted = []
 
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

        if key == "interrupted":
            return self.interrupted

        if key == "total":
            # Consistent: per-keyword total = success+failed+interrupted
            # This must equal keywords_processed after correct interrupted handling
            return (
                len(self.success)
                + len(self.failed)
                + len(self.interrupted)
            )

        raise KeyError(key)
 
    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default
 
    def _is_duplicate(self, lst, keyword, engine, thread_id=None):
        """Check duplicate by (keyword, thread_id) — engine is ignored for dedup to avoid double-count per worker.
        Same keyword on same thread is duplicate even if engine differs (youtube vs duckduckgo)."""
        kw = str(keyword)
        tid = str(thread_id) if thread_id is not None else None
        for d in lst:
            if str(d.get("keyword","")) != kw:
                continue
            # If thread_id provided, require same thread to be considered duplicate
            if tid is not None and d.get("thread_id") is not None:
                if str(d.get("thread_id")) != tid:
                    continue
                return True
            # If no thread_id, fallback to keyword+engine (legacy)
            if tid is None and str(d.get("engine","")) != str(engine):
                continue
            return True
        return False

    def record_keyword_success(self, keyword, engine="unknown", thread_id=None):
        """Record per-keyword success for tick/cross summary (like main.py)."""
        try:
            # Prevent exact duplicate (same keyword+engine+thread) from double-count
            if self._is_duplicate(self.success, keyword, engine, thread_id):
                return
            entry = {"keyword": str(keyword), "engine": str(engine)}
            if thread_id is not None:
                entry["thread_id"] = str(thread_id)
            self.success.append(entry)
        except Exception:
            pass

    def record_keyword_failed(self, keyword, engine="unknown", thread_id=None):
        """Record per-keyword failure for tick/cross summary."""
        try:
            if self._is_duplicate(self.failed, keyword, engine, thread_id):
                return
            entry = {"keyword": str(keyword), "engine": str(engine)}
            if thread_id is not None:
                entry["thread_id"] = str(thread_id)
            self.failed.append(entry)
        except Exception:
            pass

    def record_keyword_interrupted(self, keyword, engine="unknown", thread_id=None):
        """Record per-keyword interruption for tick/cross summary."""
        try:
            if self._is_duplicate(self.interrupted, keyword, engine, thread_id):
                return
            # Also don't add if already in success/failed (keyword completed)
            if self._is_duplicate(self.success, keyword, engine, thread_id) or self._is_duplicate(self.failed, keyword, engine, thread_id):
                return
            entry = {"keyword": str(keyword), "engine": str(engine)}
            if thread_id is not None:
                entry["thread_id"] = str(thread_id)
            self.interrupted.append(entry)
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
        # Kept for backward compatibility; search errors are currently
        # counted via keywords_failed / videos_not_found.
        self.search_errors += 1
 
    # ==================================
    # SUMMARY
    # ==================================
 
    def reconcile(self):
        """Ensure Keywords Processed matches Session Summary Total on interrupt/failure.
        Called before print_summary to keep both summaries consistent."""
        try:
            total = len(self.success) + len(self.failed) + len(self.interrupted)
            # If interrupted and total < keywords_processed, missing interrupted records (dedup bug)
            # We can't recover missing keywords, but we can at least make Automation Summary reflect Session Summary
            # For console consistency, ensure total_sessions and keywords_processed are not less than total
            if total > self.keywords_processed:
                self.keywords_processed = total
            if total > self.total_sessions and self.total_sessions > 0:
                # total_sessions is workers, total is keywords — they are different metrics, keep both
                pass
        except Exception:
            pass

    def print_summary(self):

        import logging
        logger = logging.getLogger(__name__)
        self.reconcile()
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
            interrupted_sorted = sorted(self.interrupted, key=lambda x: str(x.get("keyword", "")))
            if success_sorted or failed_sorted or interrupted_sorted:
                # Use print with logger-like timestamp to keep order with tick prints (all via print)
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"{ts} - INFO - " + "=" * 60, flush=True)
                print(f"{ts} - INFO - " + " Session Summary ".center(60, "="), flush=True)
                for s in success_sorted:
                    try:
                        print(f"✓ {str(s.get('keyword','')):<30} [{str(s.get('engine',''))}]", flush=True)
                    except UnicodeEncodeError:
                        print(f"[OK] {str(s.get('keyword','')):<30} [{str(s.get('engine',''))}]", flush=True)
                if success_sorted and (failed_sorted or interrupted_sorted):
                    print(flush=True)
                for f in failed_sorted:
                    try:
                        print(f"✗ {str(f.get('keyword','')):<30} [{str(f.get('engine',''))}]", flush=True)
                    except UnicodeEncodeError:
                        print(f"[FAIL] {str(f.get('keyword','')):<30} [{str(f.get('engine',''))}]", flush=True)
                if failed_sorted and interrupted_sorted:
                    print(flush=True)
                for i in interrupted_sorted:
                    try:
                        print(f"⏹ {str(i.get('keyword','')):<30} [{str(i.get('engine',''))}]", flush=True)
                    except UnicodeEncodeError:
                        print(f"[INT] {str(i.get('keyword','')):<30} [{str(i.get('engine',''))}]", flush=True)
                print(f"{ts} - INFO - " + "-" * 60, flush=True)
                try:
                    total = len(success_sorted) + len(failed_sorted) + len(interrupted_sorted)
                    print(f"{ts} - INFO - Total   : {total}", flush=True)
                    print(f"{ts} - INFO - Success : {len(success_sorted)}", flush=True)
                    print(f"{ts} - INFO - Failed  : {len(failed_sorted)}", flush=True)
                    print(f"{ts} - INFO - Interrupted : {len(interrupted_sorted)}", flush=True)
                except Exception:
                    pass
                print(f"{ts} - INFO - " + "=" * 60, flush=True)
        except Exception:
            pass
 
        print("\n")
        print("=" * 60)
        print("              AUTOMATION SUMMARY")
        print("=" * 60)

       

        # Consistency line — ties Session Summary Total to Automation Summary
        try:
            session_total = len(self.success) + len(self.failed) + len(self.interrupted)
            print(f"Session Summary Total: {session_total} (Success {len(self.success)} + Failed {len(self.failed)} + Interrupted {len(self.interrupted)})")
        except Exception:
            pass
 
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