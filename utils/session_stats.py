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
        # Error / Retry Statistics
        # --------------------------------

        self.retry_count = 0
        self.browser_errors = 0
        self.search_errors = 0

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