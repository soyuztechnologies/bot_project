"""
youtube_main.py
 
Entry point for YouTube Automation.
 
This merged version keeps the original YouTube main flow and adds
 database initialization, application logging, and cleanup.
"""
 
import json
import logging
from pathlib import Path
 
from dotenv import load_dotenv  # type: ignore
 
from utils.exceptions import (
    ConfigError,
    ConfigFileNotFoundError,
    ConfigInvalidError,
    ValidationError,
    wrap_unexpected,
)
 
from automation.youtube_session import start_parallel_sessions
from utils.database import (
    check_db_connection,
    DatabaseHandler,
    close_connection_pool,
    initialize_database,
)
from utils.logger import setup_logger
 
 
# ---------------------------------------------------------
# Base Configuration
# ---------------------------------------------------------
 
BASE_DIR = Path(__file__).resolve().parent
 
# Load environment variables from .env file
load_dotenv()
 
logger = logging.getLogger(__name__)
 
 
# ---------------------------------------------------------
# JSON Loader
# ---------------------------------------------------------
 
def load_json(path):
    """
    Load and return JSON data from the given path.
    Raises ConfigFileNotFoundError / ConfigInvalidError (expected).
    """
    path = Path(path)
    if not path.exists():
        raise ConfigFileNotFoundError(f"Required file not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError as e:
        raise ConfigInvalidError(f"Invalid JSON in {path}: {e}", cause=e) from e
    except OSError as e:
        raise ConfigError(f"Failed to read {path}: {e}", cause=e) from e
    except Exception as e:
        raise wrap_unexpected(e, f"load_json {path}") from e


def validate_youtube_config(config, keywords, search_engines):
    """Fail early with clear messages (mirrors main.py validation)."""
    required = ["browser", "sessions", "search", "youtube", "timing", "files"]
    missing = [s for s in required if s not in config]
    if missing:
        raise ValidationError(f"Missing config section(s): {', '.join(missing)}")
    if not isinstance(keywords, list) or not keywords:
        raise ValidationError("data/keywords.json must contain at least one keyword.")
    if not isinstance(search_engines, dict) or not search_engines:
        raise ValidationError("data/search_engines.json must contain at least one engine.")
    yt = config.get("youtube", {})
    if not yt.get("targetChannel"):
        raise ValidationError("youtube.targetChannel must be configured.")
    try:
        wt_min = int(yt.get("watchTimeMin", 1))
        wt_max = int(yt.get("watchTimeMax", 1))
    except (TypeError, ValueError) as e:
        raise ValidationError(f"youtube watchTime must be integers: {e}", cause=e) from e
    if wt_min < 1 or wt_max < 1 or wt_max < wt_min:
        raise ValidationError("youtube watchTimeMin/Max must be >=1 and Max >= Min.")
    try:
        parallel = int(config.get("sessions", {}).get("parallel", 1))
    except (TypeError, ValueError) as e:
        raise ValidationError(f"sessions.parallel must be integer: {e}", cause=e) from e
    if parallel < 1:
        raise ValidationError("sessions.parallel must be 1 or greater.")
 
 
# ---------------------------------------------------------
# Main
# ---------------------------------------------------------
 
def _print_youtube_summary(stats, config=None, keywords=None):
    """
    Print YouTube summary like main.py does when all keywords explored.
    Uses SessionStats.print_summary() and adds main.py-style header for consistency.
    """
    try:
        if stats is None:
            print("\n" + "=" * 60)
            print("              YOUTUBE AUTOMATION SUMMARY")
            print("=" * 60)
            print(f"Keywords configured : {len(keywords) if keywords else 0}")
            print("No stats available (automation never started).")
            print("=" * 60)
            return
        # SessionStats already has detailed summary
        if hasattr(stats, "print_summary"):
            # Add main.py-like header before detailed stats
            logger.info("\n" + "=" * 60)
            logger.info(" YouTube Session Summary ".center(60, "="))
            stats.print_summary()
            # Also log browser mode / config like main.py
            if config:
                try:
                    browser_mode = config.get("browser", {}).get("mode", "unknown")
                    logger.info(f"Browser Mode: {str(browser_mode).capitalize()}")
                    logger.info(f"Total Keywords: {len(keywords) if keywords else stats.keywords_processed}")
                    logger.info(f"Success (videos found): {getattr(stats, 'videos_found', 0)}")
                    logger.info(f"Failed (videos not found): {getattr(stats, 'videos_not_found', 0)}")
                    logger.info(f"Interrupted: {len(getattr(stats, 'interrupted', []))}")
                except Exception:
                    pass
            logger.info("=" * 60)
        elif isinstance(stats, bool):
            # Legacy bool return from start_parallel_sessions
            print("\n" + "=" * 60)
            print("              YOUTUBE AUTOMATION SUMMARY")
            print("=" * 60)
            print(f"Completed: {stats}")
            if keywords:
                print(f"Keywords: {len(keywords)}")
            print("=" * 60)
        else:
            # Fallback for unexpected type
            print(f"\nYouTube Summary (fallback): {stats}")
    except Exception as e:
        logger.error(f"Failed to print YouTube summary: {e}", exc_info=True)
        try:
            print(f"\nYouTube Summary error: {e}")
        except Exception:
            pass
 
 
def main():
    """
    Run one complete YouTube automation cycle.
 
    Keeps the original main flow:
    - Load config
    - Load keywords
    - Load search engines
    - Start parallel sessions
 
    Adds :
    - .env loading
    - application logger setup
    - database initialization
    - database connection check
    - database logging handler
    - database cleanup
    - Summary even on Ctrl+C / error (like main.py)
    """
 
    db_initialized = False
    database_handler = None
    config = None
    keywords = None
    search_engines = None
    youtube_stats = None
    completed = None
    interrupted = False
    unexpected_error = None
 
    try:
 
        # -----------------------------------------------------
        # Logging Setup
        # -----------------------------------------------------
 
        try:
            setup_logger()
        except Exception as log_error:
            # Logging setup should not stop the automation.
            print(f"Logger setup failed : {log_error}")
 
        # -----------------------------------------------------
        # Database Setup
        # -----------------------------------------------------
 
        try:
 
            initialize_database()
            db_initialized = True
 
            # Check whether database is reachable.
            check_db_connection()
 
            # Add database logging to the root logger.
            database_handler = DatabaseHandler()
            logging.getLogger().addHandler(database_handler)
 
            logger.info(
                "Database logging initialized successfully."
            )
 
        except Exception as db_error:
 
            # Database failure must NOT stop YouTube automation.
            logger.error(
                f"Database initialization failed : {db_error}",
                exc_info=True,
            )
 
            logger.info(
                "Continuing YouTube automation without database logging."
            )
 
        # -----------------------------------------------------
        # Load Configuration
        # -----------------------------------------------------
 
        config = load_json(
            BASE_DIR / "config.json"
        )
 
        # -----------------------------------------------------
        # Load Keywords
        # -----------------------------------------------------
 
        keywords = load_json(
            BASE_DIR / config["files"]["keywords"]
        )
 
        # -----------------------------------------------------
        # Load Search Engines
        # -----------------------------------------------------
 
        search_engines = load_json(
            BASE_DIR / config["files"]["searchEngines"]
        )

        validate_youtube_config(config, keywords, search_engines)

        # -----------------------------------------------------
        # Start Message
        # -----------------------------------------------------

        print("=" * 60)
        print("YouTube Automation Started")
        print("=" * 60)

        print(
            f"Browsers : "
            f"{', '.join(config.get('browser', {}).get('browsers', []) or []) if config.get('browser', {}).get('browsers') else list(config.get('browser', {}).get('distribution', {}).keys())}"
        )

        print(
            f"Sessions : "
            f"{config.get('sessions', {}).get('parallel', 1)}"
        )
 
        print(
            f"Keywords : {len(keywords)}"
        )
 
        print("=" * 60)
 
        logger.info(
            "YouTube automation started."
        )
 
        # -----------------------------------------------------
        # Start Parallel YouTube Sessions
        # -----------------------------------------------------
        #
        # IMPORTANT:
        # The merged youtube_session.py keeps the original
        # function signature:
        #
        # start_parallel_sessions(
        #     keywords,
        #     config,
        #     search_engines
        # )
        #
        # Therefore we pass search_engines here instead of
        #  stats dictionary.
        #
        # Database session records are handled inside
        # youtube_session.py.
        # start_parallel_sessions now always prints summary even on Ctrl+C/error
        # and youtube_main will also ensure summary in finally (like main.py)
        # -----------------------------------------------------
 
        result = start_parallel_sessions(
            keywords,
            config,
            search_engines,
        )
 
        # Handle both return types: bool (legacy) and SessionStats (current)
        if hasattr(result, "print_summary") or hasattr(result, "total_sessions"):
            youtube_stats = result
            # Success means no failures, no interrupts, no missing videos
            try:
                completed = (
                    youtube_stats.failed_sessions == 0
                    and youtube_stats.keywords_failed == 0
                    and len(getattr(youtube_stats, "failed", [])) == 0
                    and len(getattr(youtube_stats, "interrupted", [])) == 0
                    and getattr(youtube_stats, "videos_not_found", 0) == 0
                )
            except Exception:
                completed = False
            # start_parallel_sessions swallows Ctrl+C internally and returns
            # partial stats, so it never propagates here: infer interruption
            # from non-empty interrupted list to avoid "ended normally" lies.
            try:
                if len(getattr(youtube_stats, "interrupted", []) or []) > 0:
                    interrupted = True
            except Exception:
                pass
        else:
            completed = bool(result)
            # For bool version, stats already printed inside youtube_session
            # Keep youtube_stats None but completed indicates status
 
        # -----------------------------------------------------
        # Completion Status
        # -----------------------------------------------------
 
        if completed:
 
            print("\nCycle completed.")
            print(
                "Automation completed successfully."
            )
 
            logger.info(
                "YouTube automation cycle completed successfully."
            )
 
        else:
 
            # Could be interrupted or failed - but not necessarily user stop; check interrupted flag later
            if not interrupted and unexpected_error is None:
                print(
                    "\nAutomation completed with some failures."
                )
                logger.info(
                    "YouTube automation completed with failures."
                )
 
    except KeyboardInterrupt:
        interrupted = True
        print(
            "\nAutomation stopped by user (Ctrl+C)."
        )
 
        logger.info(
            "YouTube automation stopped by user (Ctrl+C)."
        )
 
    except Exception as error:
        unexpected_error = error
        print(
            f"\nUnexpected Error : {error}"
        )
 
        logger.error(
            f"Unexpected YouTube automation error : {error}",
            exc_info=True,
        )
 
    finally:

        # -----------------------------------------------------
        # Always ensure summary is visible — but youtube_session already
        # printed Session Summary + Automation Summary in its finally.
        # Avoid duplicate full summary; just add a concise final status line
        # consistent with main.py (seo) flow.
        # -----------------------------------------------------
        try:
            if youtube_stats is not None and hasattr(youtube_stats, "print_summary"):
                # Session already printed detailed summary — only add one-line final status
                # (no duplicate full summary)
                if interrupted:
                    print(f"\nYouTube final status: interrupted (Ctrl+C)")
                elif youtube_stats.failed_sessions == 0 and youtube_stats.keywords_failed == 0 and len(youtube_stats.interrupted) == 0:
                    print(f"\nYouTube final status: completed")
                else:
                    print(f"\nYouTube final status: completed with failures/interruptions")
            elif youtube_stats is not None:
                _print_youtube_summary(youtube_stats, config, keywords)
            elif completed is not None:
                # Bool version already printed summary in session; just final line
                print(f"\nYouTube final status: {'completed' if completed else 'stopped/failed'}")
            elif interrupted:
                print("\n=== YouTube Automation Interrupted (Ctrl+C) ===")
                if keywords:
                    print(f"Keywords configured: {len(keywords)}")
                print("No stats yet — automation stopped before sessions started.")
            elif unexpected_error is not None:
                print(f"\n=== YouTube Automation Failed: {unexpected_error} ===")
                if keywords:
                    print(f"Keywords configured: {len(keywords)}")
        except Exception as summary_err:
            logger.error(f"Failed to print YouTube final summary: {summary_err}", exc_info=True)

        # -----------------------------------------------------
        # Database Cleanup — rely on database.py log, avoid duplicate logger.info
        # -----------------------------------------------------

        if db_initialized:

            try:

                close_connection_pool()

            except Exception as db_error:

                logger.error(
                    f"Failed to close database connection pool : "
                    f"{db_error}",
                    exc_info=True,
                )
 
        if interrupted:
            logger.info("YouTube automation ended due to interruption.")
        elif unexpected_error is not None:
            logger.info("YouTube automation ended due to unexpected error.")
        else:
            logger.info("YouTube automation ended normally.")
 
 
# ---------------------------------------------------------
# Entry Point
# ---------------------------------------------------------
 
if __name__ == "__main__":
    main()