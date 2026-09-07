"""
main.py
 
Project Entry Point
 
Responsibilities:
1. Load configuration files.
2. Load keywords
3. Load search engine settings.
"""
 
import json
import logging
from pathlib import Path
from dotenv import load_dotenv
from automation.session import start_parallel_sessions
from utils.database import check_db_connection, initialize_database, DatabaseHandler, close_connection_pool
from utils.logger import setup_logger
from utils.exceptions import (
    BrowserError,
    CaptchaDetectedError,
    ConfigError,
    ConfigFileNotFoundError,
    ConfigInvalidError,
    DatabaseError,
    DatabaseUnavailableError,
    SearchEngineError,
    SeoBotError,
    TargetNotFoundError,
    UnhandledAutomationError,
    ValidationError,
    wrap_unexpected,
)
 
 
# Load environment variables from .env file
load_dotenv()
 
logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent
 
 
def load_json(file_path):
    """
    Load and return JSON data.
    Raises: ConfigFileNotFoundError (expected), ConfigInvalidError (expected) for JSON errors.
    """
    file_path = Path(file_path)
 
    if not file_path.exists():
        raise ConfigFileNotFoundError(f"Required file not found: {file_path}")
 
    try:
        with file_path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError as e:
        raise ConfigInvalidError(f"Invalid JSON in {file_path}: {e}", cause=e) from e
    except OSError as e:
        raise ConfigError(f"Failed to read {file_path}: {e}", cause=e) from e
    except Exception as e:
        raise wrap_unexpected(e, f"load_json {file_path}") from e
 
 
def project_path(relative_path):
    """Resolve a config path relative to this project folder."""
 
    return BASE_DIR / relative_path
 
 
def validate_config(config, keywords, search_engines):
    """Fail early with clear messages for missing or invalid config values.
    Raises: ValidationError/ConfigError (expected)
    """
 
    required_sections = ["browser", "sessions", "search", "website", "timing", "files"]
    missing_sections = [
        section for section in required_sections if section not in config
    ]
 
    if missing_sections:
        raise ValidationError(f"Missing config section(s): {', '.join(missing_sections)}")
 
    if not isinstance(keywords, list) or not keywords:
        raise ValidationError("data/keywords.json must contain at least one keyword.")
 
    engine_names = get_search_engine_names(config, search_engines)
 
    if not engine_names:
        raise ValidationError("Configure at least one search engine in search.engines.")
 
    missing_engines = [
        engine_name for engine_name in engine_names if engine_name not in search_engines
    ]
 
    if missing_engines:
        available = ", ".join(sorted(search_engines))
        raise ValidationError(
            "Search engine(s) not configured: "
            f"{', '.join(missing_engines)}. Available: {available}"
        )
 
    for engine_name in engine_names:
        validate_search_engine(engine_name, search_engines[engine_name])
 
    validate_website_config(config["website"])
 
    try:
        parallel_sessions = int(config["sessions"].get("parallel", 1))
    except (TypeError, ValueError) as e:
        raise ValidationError(f"sessions.parallel must be integer: {e}", cause=e) from e
 
    if parallel_sessions < 1:
        raise ValidationError("sessions.parallel must be 1 or greater.")
 
    try:
        max_pages = int(config["search"].get("maxPages", 1))
    except (TypeError, ValueError) as e:
        raise ValidationError(f"search.maxPages must be integer: {e}", cause=e) from e
 
    if max_pages < 1:
        raise ValidationError("search.maxPages must be 1 or greater.")
 
 
def validate_search_engine(engine_name, engine):
    """Validate one data/search_engines.json entry.
    Raises: ValidationError (expected)
    """
 
    if "url" not in engine:
        raise ValidationError(f"Search engine '{engine_name}' is missing 'url'.")
 
    if "resultLinks" not in engine:
        raise ValidationError(f"Search engine '{engine_name}' is missing 'resultLinks'.")
 
    if "searchUrl" not in engine and "searchBox" not in engine:
        raise ValidationError(
            f"Search engine '{engine_name}' needs either 'searchUrl' or 'searchBox'."
        )
 
    for locator_name in ("searchBox", "nextButton", "resultLinks"):
        locator = engine.get(locator_name)
 
        if not locator:
            continue
 
        if "by" not in locator or "value" not in locator:
            raise ValidationError(
                f"Search engine '{engine_name}' locator '{locator_name}' "
                "must include 'by' and 'value'."
            )
 
 
def validate_website_config(website_config):
    """Validate the 'website' section of the config.
    Raises: ValidationError (expected)
    """
    if not website_config.get("domain"):
        raise ValidationError("website.domain must be configured with your target domain.")
 
    if "internal_links" in website_config:
        internal_links_config = website_config["internal_links"]
 
        if not isinstance(internal_links_config.get("enabled"), bool):
            raise ValidationError(
                "website.internal_links.enabled must be a boolean (true/false)."
            )
 
        if internal_links_config.get("enabled"):
            max_to_visit = internal_links_config.get("max_to_visit")
            if not isinstance(max_to_visit, int) or max_to_visit < 0:
                raise ValidationError(
                    "website.internal_links.max_to_visit must be a non-negative integer."
                )
 
            selectors = internal_links_config.get("selectors")
            if not isinstance(selectors, list) or not selectors:
                raise ValidationError(
                    "website.internal_links.selectors must be a non-empty list of XPath selectors."
                )
 
 
def get_search_engine_names(config, search_engines):
    """Return the configured search engines to rotate across sessions."""
 
    configured_engines = config["search"].get("engines")
 
    if configured_engines:
        if isinstance(configured_engines, str):
            if configured_engines.lower() == "all":
                return list(search_engines.keys())
 
            return [configured_engines]
 
        engine_names = list(configured_engines)
 
        if any(str(engine_name).lower() == "all" for engine_name in engine_names):
            return list(search_engines.keys())
 
        return engine_names
 
    engine_name = config["search"].get("engine")
 
    if engine_name:
        return [engine_name]
 
    return list(search_engines.keys())
 
 
def print_summary(stats, config):
    """Prints a formatted summary of the automation results."""
    success_sessions = stats.get("success", [])
    failed_sessions = stats.get("failed", [])
    interrupted_sessions = stats.get("interrupted", [])
    total_sessions = stats.get("total", len(success_sessions) + len(failed_sessions) + len(interrupted_sessions))
    success_count = len(success_sessions)
    failed_count = len(failed_sessions)
    interrupted_count = len(interrupted_sessions)
 
    # Sort for consistent output
    try:
        success_sessions.sort(key=lambda x: str(x.get("keyword", "")))
    except Exception:
        pass
    try:
        failed_sessions.sort(key=lambda x: str(x.get("keyword", "")))
    except Exception:
        pass
    try:
        interrupted_sessions.sort(key=lambda x: str(x.get("keyword", "")))
    except Exception:
        pass
 
    # Use print with logger-like timestamp for all summary parts to keep order (even on Ctrl+C/error)
    # This ensures tick/cross appear between header and footer like user's example
    import sys
    from datetime import datetime
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{ts} - INFO - " + "=" * 50, flush=True)
    print(f"{ts} - INFO - " + " Session Summary ".center(50, "="), flush=True)
    for session in success_sessions:
        try:
            print(f"✓ {session['keyword']:<30} [{session['engine']}]", flush=True)
        except UnicodeEncodeError:
            print(f"[OK] {session['keyword']:<30} [{session['engine']}]", flush=True)
        except Exception:
            try:
                print(str(session), flush=True)
            except Exception:
                pass
 
    if success_sessions and failed_sessions:
        print(flush=True)
 
    for session in failed_sessions:
        try:
            print(f"✗ {session['keyword']:<30} [{session['engine']}]", flush=True)
        except UnicodeEncodeError:
            print(f"[FAIL] {session['keyword']:<30} [{session['engine']}]", flush=True)
        except Exception:
            try:
                print(str(session), flush=True)
            except Exception:
                pass
 
    if failed_sessions and interrupted_sessions:
        print(flush=True)

    for session in interrupted_sessions:
        try:
            print(f"⏹ {session['keyword']:<30} [{session['engine']}]", flush=True)
        except UnicodeEncodeError:
            print(f"[INT] {session['keyword']:<30} [{session['engine']}]", flush=True)
        except Exception:
            try:
                print(str(session), flush=True)
            except Exception:
                pass

    if interrupted_sessions and (success_sessions or failed_sessions):
        print(flush=True)

    print(f"{ts} - INFO - " + "-" * 50, flush=True)
    print(f"{ts} - INFO - Browser Mode: {config['browser']['mode'].capitalize()}", flush=True)
    print(f"{ts} - INFO - Total   : {total_sessions}", flush=True)
    print(f"{ts} - INFO - Success : {success_count}", flush=True)
    print(f"{ts} - INFO - Failed  : {failed_count}", flush=True)
    print(f"{ts} - INFO - Interrupted : {interrupted_count}", flush=True)
    print(f"{ts} - INFO - " + "=" * 50, flush=True)
 
 
def main():
    """Main function to run the SEO automation bot."""
    stats = None
    config = None
    interrupted = False
    unexpected_error = None
    try:
        setup_logger()
 
        # Add the custom database handler to the root logger.
        # This will capture logs from the entire application.
        logging.getLogger().addHandler(DatabaseHandler())
        # Initialize database and then check the connection
        initialize_database()
        check_db_connection()
        logger.info("=" * 50)
        logger.info("Automation Project Started")
        logger.info("=" * 50)
 
        # Load main config
        config = load_json(BASE_DIR / "config.json")
 
        # Load project data
        keywords = load_json(project_path(config["files"]["keywords"]))
        search_engines = load_json(project_path(config["files"]["searchEngines"]))
 
        validate_config(config, keywords, search_engines)
 
        engine_names = get_search_engine_names(config, search_engines)
 
        logger.info(f"Project Path      : {BASE_DIR}")
        logger.info(f"Search Engines    : {', '.join(engine_names)}")
        logger.info(f"Browser Mode      : {config['browser']['mode'].capitalize()}")
        logger.info(f"Parallel Sessions : {config['sessions']['parallel']}")
        logger.info(f"Keywords          : {len(keywords)}")
 
        # Start automation
        stats = start_parallel_sessions(
            keywords,
            config,
            search_engines,
            engine_names,
        )
 
    except KeyboardInterrupt:
        interrupted = True
        # Silence retry spam immediately on Ctrl+C before any driver cleanup
        try:
            from utils.logger import silence_noisy_loggers
            silence_noisy_loggers()
        except Exception:
            pass
        try:
            import logging as _logging
            for _n in ("urllib3", "urllib3.connectionpool", "selenium", "selenium.webdriver.remote.remote_connection"):
                _logging.getLogger(_n).setLevel(_logging.ERROR)
        except Exception:
            pass
        logger.info("\nAutomation stopped by user (Ctrl+C).")
    except (ConfigError, ValidationError) as error:
        # Expected config errors — graceful, user-friendly
        unexpected_error = error
        logger.error(f"Configuration error: {error} [{type(error).__name__}]", exc_info=False)
        print(f"\nConfiguration error: {error}")
    except (DatabaseError, DatabaseUnavailableError) as error:
        # Expected DB unavailable — continue without DB is not possible at top level, but log gracefully
        unexpected_error = error
        logger.error(f"Database error: {error} [{type(error).__name__}]", exc_info=True)
        print(f"\nDatabase error: {error} — check .env and DB availability")
    except (BrowserError, SearchEngineError, CaptchaDetectedError, TargetNotFoundError) as error:
        # Expected automation business failures — should have been handled per-session, but if bubbled to top, treat as graceful
        unexpected_error = error
        logger.warning(f"Automation business failure at top level: {error} [{type(error).__name__}]", exc_info=False)
        print(f"\nAutomation business failure: {error}")
    except UnhandledAutomationError as error:
        # Wrapped unexpected (must come before SeoBotError: it subclasses SeoBotError)
        unexpected_error = error
        logger.error(f"Unhandled automation error: {error} cause={error.cause} [{type(error).__name__}]", exc_info=True)
    except SeoBotError as error:
        # Any other expected SeoBotError
        unexpected_error = error
        logger.error(f"Automation expected failure: {error} [{type(error).__name__}]", exc_info=False)
    except Exception as error:
        # Truly unexpected bug — wrap and log with traceback, but don't crash silently
        wrapped = wrap_unexpected(error, "main")
        unexpected_error = wrapped
        logger.error(f"Unexpected automation error (bug): {wrapped} cause={error} [{type(error).__name__}]", exc_info=True)
    finally:
        # Always print summary if automation was started (even on Ctrl+C or error)
        if stats is not None and config is not None:
            try:
                print_summary(stats, config)
            except (SeoBotError, ValidationError) as summary_error:
                logger.error(f"Failed to print summary (expected): {summary_error} [{type(summary_error).__name__}]", exc_info=False)
            except UnhandledAutomationError as summary_error:
                logger.error(f"Failed to print summary (unhandled): {summary_error} cause={summary_error.cause}", exc_info=True)
            except Exception as summary_error:
                wrapped = wrap_unexpected(summary_error, "print_summary")
                logger.error(f"Failed to print summary (bug): {wrapped}", exc_info=True)
                # Fallback console print if logger fails
                try:
                    total = stats.get("total", 0) if isinstance(stats, dict) else getattr(stats, "total_sessions", 0)
                    print(f"\nSummary fallback: total={total}")
                except Exception:
                    pass
        elif interrupted:
            logger.info("No summary: automation was interrupted before stats were available.")
            print("\n=== No stats available (interrupted before start) ===")
        elif unexpected_error is not None:
            # For expected ConfigError etc., already logged; give user-friendly fallback
            if isinstance(unexpected_error, (ConfigError, ValidationError)):
                print(f"\n=== No stats: configuration error — {unexpected_error} ===")
            else:
                logger.info("No summary: automation failed before stats were available.")
                print(f"\n=== No stats available (error: {unexpected_error}) ===")
 
        # start_parallel_sessions swallows Ctrl+C internally and returns partial
        # stats, so infer interruption from non-empty interrupted list.
        try:
            if not interrupted and isinstance(stats, dict) and len(stats.get("interrupted", []) or []) > 0:
                interrupted = True
        except Exception:
            pass

        if interrupted:
            logger.info("Automation ended due to interruption.")
        elif unexpected_error is not None:
            if isinstance(unexpected_error, (ConfigError, ValidationError)):
                logger.info("Automation ended due to configuration error.")
            elif isinstance(unexpected_error, DatabaseError):
                logger.info("Automation ended due to database error.")
            elif isinstance(unexpected_error, SeoBotError):
                logger.info(f"Automation ended due to expected failure: {type(unexpected_error).__name__}")
            else:
                logger.info("Automation ended due to unexpected error.")
        else:
            logger.info("Automation ended normally.")
 
        logger.info("Automation Project Finished.")
        try:
            close_connection_pool()
        except DatabaseError as e:
            logger.warning(f"Failed to close DB pool (expected DB error): {e} [{type(e).__name__}]", exc_info=False)
        except Exception as e:
            wrapped = wrap_unexpected(e, "close_connection_pool")
            logger.warning(f"Failed to close DB pool (bug): {wrapped}", exc_info=True)
 
if __name__ == "__main__":
    main()