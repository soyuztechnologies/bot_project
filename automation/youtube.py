"""
youtube.py

This module contains generic YouTube automation functions.

Responsibilities:
1. Open YouTube.
2. Search keyword.
3. Find target channel video.
4. Watch the opened video.
"""

import json
from pathlib import Path

from automation.search_engine import (
    wait_for_element,
    wait_for_elements,
)

from utils.helpers import (
    human_typing,
    press_enter,
    random_sleep,
    scroll_and_click,
)

BASE_DIR = Path(__file__).resolve().parents[1]


def load_youtube_config():
    """
    Load YouTube configuration.
    """

    with open(
        BASE_DIR / "data" / "youtube.json",
        encoding="utf-8",
    ) as file:
        return json.load(file)


YOUTUBE = load_youtube_config()


def open_youtube(driver):
    """
    Open YouTube home page.
    """

    driver.get(YOUTUBE["url"])


def search_video(driver, keyword, config, stop_event=None):
    """
    Search keyword on YouTube.
    """

    search_box = wait_for_element(
        driver,
        YOUTUBE["searchBox"],
    )

    search_box.clear()

    human_typing(
        search_box,
        keyword,
        config["timing"]["typingMin"],
        config["timing"]["typingMax"],
        stop_event,
    )

    if stop_event and stop_event.is_set():
        return

    press_enter(search_box)

    random_sleep(
        config["timing"]["sleepMin"],
        config["timing"]["sleepMax"],
        stop_event,
    )


def get_video_cards(driver):
    """
    Return all visible video cards.
    """

    try:
        return wait_for_elements(
            driver,
            YOUTUBE["videoCards"],
        )

    except Exception:
        return []


def get_video_title(video):
    """
    Return video title element and text.
    """

    title_element = video.find_element(
        "css selector",
        YOUTUBE["videoTitle"]["value"],
    )

    return (
        title_element,
        title_element.text.strip(),
    )


# def get_channel_name(video):
#     """
#     Return channel name.
#     """

#     channel_element = video.find_element(
#         "css selector",
#         YOUTUBE["channelName"]["value"],
#     )

#     return channel_element.text.strip()

def get_channel_name(video):
    """
    Return channel name.
    """

    try:
        channel_element = video.find_element(
            "css selector",
            YOUTUBE["channelName"]["value"],
        )

        return channel_element.get_attribute("textContent").strip()

    except Exception:
        return ""

def find_target_video(driver, config, stop_event=None):
    """
    Find the first video uploaded by the target channel.
    """

    youtube_config = config["youtube"]

    target_channel = youtube_config["targetChannel"]

    max_scrolls = youtube_config["maxScrolls"]

    checked = set()

    for scroll in range(max_scrolls):

        if stop_event and stop_event.is_set():
            return False

        print(f"\nScroll {scroll + 1}/{max_scrolls}")

        videos = get_video_cards(driver)

        for video in videos:

            try:

                title_element, title = get_video_title(video)

                channel = get_channel_name(video)

                key = f"{title}|{channel}"

                if key in checked:
                    continue

                checked.add(key)

                print(f"Checking : {title}")
                print(f"Channel  : {channel}")
                print(f"Target : {target_channel}")

                if target_channel.lower() in channel.lower():

                    print(f"\nTarget channel found : {channel}")
                    print(f"Opening video : {title}")

                    scroll_and_click(
                        driver,
                        title_element,
                    )

                    random_sleep(
                        config["timing"]["sleepMin"],
                        config["timing"]["sleepMax"],
                        stop_event,
                    )

                    return True

            except Exception as error:

                print(f"Skipping video : {error}")

                continue

        driver.execute_script(
            "window.scrollBy(0, window.innerHeight);"
        )

        random_sleep(
            config["timing"]["sleepMin"],
            config["timing"]["sleepMax"],
            stop_event,
        )

    return False


def watch_video(driver, config, stop_event=None):
    """
    Watch opened YouTube video for a random duration.
    """

    import random
    import time

    watch_time = random.randint(
        config["youtube"]["watchTimeMin"],
        config["youtube"]["watchTimeMax"],
    )

    print(f"\nWatching video for {watch_time} seconds...")

    start_time = time.time()

    while (time.time() - start_time) < watch_time:

        if stop_event and stop_event.is_set():
            return

        try:

            driver.execute_script(
                """
                window.scrollBy(
                    0,
                    Math.floor(Math.random()*300)
                );
                """
            )

        except Exception:
            pass

        random_sleep(
            config["timing"]["sleepMin"],
            config["timing"]["sleepMax"],
            stop_event,
        )

    print("Finished watching video.")