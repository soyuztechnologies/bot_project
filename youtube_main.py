"""
youtube_main.py

Entry point for YouTube Automation.
"""

import json
from pathlib import Path

from automation.youtube_session import start_parallel_sessions

BASE_DIR = Path(__file__).resolve().parent


def load_json(path):

    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def main():

    config = load_json(BASE_DIR / "config.json")

    keywords = load_json(
        BASE_DIR / config["files"]["keywords"]
    )

    print("=" * 60)
    print("YouTube Automation Started")
    print("=" * 60)
    print(f"Browser  : {config['browser']['name']}")
    print(f"Sessions : {config['sessions']['parallel']}")
    print(f"Keywords : {len(keywords)}")
    print("=" * 60)

    start_parallel_sessions(
        keywords,
        config,
    )


if __name__ == "__main__":
    main()