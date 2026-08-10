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

    try:

        config = load_json(BASE_DIR / "config.json")

        keywords = load_json(
            BASE_DIR / config["files"]["keywords"]
        )

        search_engines = load_json(
            BASE_DIR / config["files"]["searchEngines"]
        )

        print("=" * 60)
        print("YouTube Automation Started")
        print("=" * 60)
        print(f"Browsers : {', '.join(config['browser']['browsers'])}")
        print(f"Sessions : {config['sessions']['parallel']}")
        print(f"Keywords : {len(keywords)}")
        print("=" * 60)

        completed = start_parallel_sessions(
              keywords,
              config,
        )

        if completed:
          print("\nCycle completed.")
          print("Automation completed successfully.")
        else:
         print("\nAutomation stopped by user.")

    except KeyboardInterrupt:

        print("\nAutomation stopped by user.")

    except Exception as error:

        print(f"\nUnexpected Error : {error}")


if __name__ == "__main__":
    main()