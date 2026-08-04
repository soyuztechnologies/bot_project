"""
youtube_main.py

Entry point for YouTube Automation.
"""

import json
import time
from pathlib import Path

from automation.youtube_session import start_parallel_sessions

BASE_DIR = Path(__file__).resolve().parent


def load_json(path):

    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def main():

    while True:

        try:

            config = load_json(BASE_DIR / "config.json")

            keywords = load_json(
                BASE_DIR / config["files"]["keywords"]
            )

            print("=" * 60)
            print("YouTube Automation Started")
            print("=" * 60)
            print(f"Browsers : {', '.join(config['browser']['browsers'])}")
            print(f"Sessions : {config['sessions']['parallel']}")
            print(f"Keywords : {len(keywords)}")
            print("=" * 60)

            start_parallel_sessions(
                keywords,
                config,
            )

            print("\nCycle completed.")
            print("Waiting 5 minutes before next cycle...\n")

            time.sleep(300)

        except KeyboardInterrupt:

            print("\nAutomation stopped by user.")
            break

        except Exception as error:

            print(f"\nUnexpected Error : {error}")

            print("Restarting automation in 30 seconds...\n")

            time.sleep(30)

if __name__ == "__main__":
    main()