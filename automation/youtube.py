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
from selenium.webdriver.common.by import By

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


def open_youtube(driver, config, stop_event=None):
    """
    Open YouTube home page.
    """

    driver.get(YOUTUBE["url"])

    random_sleep(
        config["timing"]["sleepMin"],
        config["timing"]["sleepMax"],
        stop_event,
    )


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
    Return all visible YouTube search results
    (videos + courses).
    """

    try:

        video_cards = driver.find_elements(
            By.CSS_SELECTOR,
            "ytd-video-renderer"
        )

        course_cards = driver.find_elements(
            By.CSS_SELECTOR,
            "yt-lockup-view-model"
        )

        # print(f"\nVideos Found  : {len(video_cards)}")
        # print(f"Courses Found : {len(course_cards)}")

        return video_cards + course_cards

    except Exception:
        return []


def get_video_title(result):
    """
    Return title element and text for both
    videos and courses.
    """

    if result.tag_name == "ytd-video-renderer":

        title = result.find_element(
            "css selector",
            "#video-title"
        )

        return title, title.text.strip()

    elif result.tag_name == "yt-lockup-view-model":

        title = result.find_element(
            "css selector",
            ".ytLockupMetadataViewModelTitle"
        )

        return title, title.text.strip()

    raise Exception("Unsupported result type")
   


def get_channel_name(result):
    """
    Return channel name for videos and courses.
    """

    if result.tag_name == "ytd-video-renderer":

        try:

            return result.find_element(
                "css selector",
                "#channel-name a"
            ).text.strip()

        except Exception:
            return ""

    elif result.tag_name == "yt-lockup-view-model":

        try:

            return result.find_element(
                "css selector",
                "a[href^='/@']"
            ).text.strip()

        except Exception:
            return ""

    return ""


def find_target_video(driver, config, stop_event=None):
    """
    Find the first video/course uploaded by the target channel.
    """

    target_channel = config["youtube"]["targetChannel"]

    checked = set()
    last_height = 0

    while True:

        if stop_event and stop_event.is_set():
            return False

        videos = get_video_cards(driver)

        if not videos:
            return False

        # Check visible results one by one
        for index in range(len(videos)):

            if stop_event and stop_event.is_set():
                return False

            # Refresh elements to avoid stale element errors
            videos = get_video_cards(driver)

            if index >= len(videos):
                break

            video = videos[index]

            try:
                channel = get_channel_name(video)
                title_element, title = get_video_title(video)

            except Exception:
                continue

            if not title.strip() or not channel.strip():
                continue

            key = f"{title}|{channel}"

            if key in checked:
                continue

            checked.add(key)

            print(f"Checking : {title}")
            print(f"Channel  : {channel}")

            # Human reading pause
            random_sleep(
                0.4,
                0.8,
                stop_event,
            )

            if target_channel.lower() in channel.lower():

                print(f"\nTarget channel found : {channel}")

                # Small pause before click
                random_sleep(
                    1,
                    2,
                    stop_event,
                )

                print(f"Opening : {title}")

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

            # Scroll a little after every 3 checked cards
            if (index + 1) % 3 == 0:

                driver.execute_script(
                    "window.scrollBy(0, 350);"
                )

                random_sleep(
                    0.5,
                    1,
                    stop_event,
                )

        # After checking current screen, move to next screen
        driver.execute_script(
            "window.scrollBy(0, window.innerHeight);"
        )

        random_sleep(
            config["timing"]["sleepMin"],
            config["timing"]["sleepMax"],
            stop_event,
        )

        new_height = driver.execute_script(
            "return document.documentElement.scrollHeight"
        )

        if new_height == last_height:

            print("\nReached end of search results.")
            return False

        last_height = new_height




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

        random_sleep(
            config["timing"]["sleepMin"],
            config["timing"]["sleepMax"],
            stop_event,
        )

    print("Finished watching video.")
    print("Returning to YouTube home...")
    

def go_to_home(driver, config, stop_event=None):
    """
    Return to YouTube home page by clicking the logo.
    """
    print("Inside go_to_home()")

    try:

        logo = wait_for_element(
            driver,
            YOUTUBE["youtubeLogo"],
        )

        print("YouTube logo Found.")

        scroll_and_click(
            driver,
            logo,
        )

        print("YouTube logo clicked.")

        random_sleep(
            config["timing"]["sleepMin"],
            config["timing"]["sleepMax"],
            stop_event,
        )

    except Exception as error:

        print(f"Failed to return to home page : {error}")




def close_mini_player(driver):
    """
    Close YouTube mini player if it is open.
    """

    try:

        close_btn = driver.find_element(
            By.CSS_SELECTOR,
            "button.ytp-miniplayer-close-button"
        )

        close_btn.click()

        print("Mini player closed.")

    except Exception:
        pass