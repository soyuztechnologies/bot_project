"""
launcher.py
 
Launcher for SEO Automation.
 
Allows user to choose which automation to run.
"""
 
from main import main as website_main
from youtube_main import main as youtube_main
from utils.exceptions import ConfigError, DatabaseError, SeoBotError, UnhandledAutomationError, wrap_unexpected
import logging
 
logger = logging.getLogger(__name__)
 
 
def main():
 
    print("\n" + "=" * 50)
    print("        SEO AUTOMATION BOT")
    print("=" * 50)
    print("1. Website Automation")
    print("2. YouTube Automation")
    print("=" * 50)
 
    try:
        choice = input("Enter your choice (1 or 2): ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nInput cancelled by user.")
        logger.info("Launcher interrupted during input.")
        return
    except Exception as e:
        wrapped = wrap_unexpected(e, "launcher input")
        logger.error(f"Launcher input unexpected error: {wrapped}", exc_info=True)
        print(f"\nUnexpected input error: {e}")
        return
 
    try:
        if choice == "1":
            print("\nStarting Website Automation...\n")
            website_main()
 
        elif choice == "2":
            print("\nStarting YouTube Automation...\n")
            youtube_main()
 
        else:
            print("\nInvalid choice.")
    except (ConfigError, DatabaseError, SeoBotError) as e:
        # Expected business failures — graceful, user-friendly
        logger.warning(f"Launcher caught expected failure: {e} [{type(e).__name__}]", exc_info=False)
        print(f"\nLauncher: {type(e).__name__}: {e}")
    except UnhandledAutomationError as e:
        logger.error(f"Launcher unhandled automation error: {e} cause={e.cause}", exc_info=True)
        print(f"\nLauncher unhandled error: {e}")
    except KeyboardInterrupt:
        print("\nLauncher interrupted by user (Ctrl+C).")
        logger.info("Launcher interrupted by user.")
    except Exception as e:
        wrapped = wrap_unexpected(e, "launcher automation")
        logger.error(f"Launcher unexpected bug: {wrapped}", exc_info=True)
        print(f"\nLauncher unexpected error: {e}")
 
 
if __name__ == "__main__":
    main()