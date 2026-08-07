"""
launcher.py

Launcher for SEO Automation.

Allows user to choose which automation to run.
"""

from main import main as website_main
from youtube_main import main as youtube_main


def main():

    print("\n" + "=" * 50)
    print("        SEO AUTOMATION BOT")
    print("=" * 50)
    print("1. Website Automation")
    print("2. YouTube Automation")
    print("=" * 50)

    choice = input("Enter your choice (1 or 2): ").strip()

    if choice == "1":
        print("\nStarting Website Automation...\n")
        website_main()

    elif choice == "2":
        print("\nStarting YouTube Automation...\n")
        youtube_main()

    else:
        print("\nInvalid choice.")


if __name__ == "__main__":
    main()