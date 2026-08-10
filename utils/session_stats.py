"""
session_stats.py

Collect automation statistics and print
a summary after all sessions complete.
"""


class SessionStats:

    def __init__(self):

        self.total_sessions = 0
        self.successful_sessions = 0
        self.failed_sessions = 0

        self.total_keywords = 0
        self.keywords_processed = 0

        self.videos_found = 0
        self.videos_not_found = 0

        self.total_watch_time = 0

        self.browser_usage = {}

        self.retry_count = 0

        self.browser_errors = 0

        self.search_errors = 0

    def record_browser(self, browser):

        self.total_sessions += 1

        self.browser_usage[browser] = (
            self.browser_usage.get(browser, 0) + 1
        )

    def record_keyword(self):

        self.keywords_processed += 1

    def record_video_found(self):

        self.videos_found += 1

    def record_video_not_found(self):

        self.videos_not_found += 1

    def record_watch_time(self, seconds):

        self.total_watch_time += seconds

    def record_retry(self):

        self.retry_count += 1

    def record_success(self):

        self.successful_sessions += 1

    def record_failure(self):

        self.failed_sessions += 1

    def print_summary(self):

        print("\n")
        print("=" * 60)
        print("              AUTOMATION SUMMARY")
        print("=" * 60)

        print(f"Sessions Started     : {self.total_sessions}")
        print(f"Successful Sessions  : {self.successful_sessions}")
        print(f"Failed Sessions      : {self.failed_sessions}")

        print("\nBrowser Usage")

        for browser, count in self.browser_usage.items():
           print(f"  {browser:<10}: {count}")

        print("\nKeywords")

        print(f"  Processed          : {self.keywords_processed}")

        print("\nVideos")

        print(f"  Found              : {self.videos_found}")
        print(f"  Not Found          : {self.videos_not_found}")

        print("\nWatch Time")

        print(f"  Total              : {self.total_watch_time} sec")

        print("\nRetries")

        print(f"  Retry Count        : {self.retry_count}")

        print("=" * 60)