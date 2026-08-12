"""
youtube.py

This module contains generic YouTube automation functions.

Responsibilities:
1. Open YouTube.
2. Search keyword.
3. Find target channel video.
4. Watch the opened video.
"""

import logging
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
logger = logging.getLogger(__name__)


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


def open_youtube(driver, config, stop_event=None, session_logger=None):
    """
    Open YouTube home page.
    """
    if session_logger:
        session_logger.info(f"Opening YouTube: {YOUTUBE['url']}", extra={'action': 'YOUTUBE_OPEN', 'status': 'RUNNING', 'url': YOUTUBE['url']})

    driver.get(YOUTUBE["url"])

    random_sleep(
        config["timing"]["sleepMin"],
        config["timing"]["sleepMax"],
        stop_event,
    )
    if session_logger:
        session_logger.info("YouTube home page opened.", extra={'action': 'YOUTUBE_OPEN', 'status': 'SUCCESS', 'url': driver.current_url})


def search_video(driver, keyword, config, stop_event=None, session_logger=None):
    """
    Search keyword on YouTube.
    """
    if session_logger:
        session_logger.info(f"Searching for video with keyword: '{keyword}'",
                            extra={'action': 'VIDEO_SEARCH_STARTED', 'status': 'RUNNING'})


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
    )  # This sleep is after the search is initiated.
    if session_logger:
        session_logger.info(f"Video search for '{keyword}' initiated.", extra={'action': 'VIDEO_SEARCH_STARTED', 'status': 'SUCCESS'})

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


def find_target_video(driver, config, stop_event, session_logger):
    """
    Find the first video/course uploaded by the target channel.
    """

    target_channel = config["youtube"]["targetChannel"]

    session_logger.info(f"Scanning results for target channel: '{target_channel}'", extra={'action': 'SCAN_FOR_CHANNEL', 'status': 'RUNNING'})
    checked = set()
    last_height = 0

    while True:

        if stop_event.is_set():
            return False

        videos = get_video_cards(driver)

        if not videos:
            session_logger.warning("No video cards found on the page.")
            return False

        # Check visible results one by one
        for index in range(len(videos)):

            if stop_event.is_set():
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

            # This is very verbose, so using DEBUG level.
            session_logger.debug(f"Checking video: '{title}' by '{channel}'")

            # Human reading pause
            random_sleep(
                0.4,
                0.8,
                stop_event,
            )

            if target_channel.lower() in channel.lower():
                # Small pause before click
                random_sleep(
                    1,
                    2,
                    stop_event,
                )
                session_logger.info(f"Target channel video found: '{title}'")
                session_logger.info(f"Opening video: {title}", extra={'action': 'OPEN_VIDEO', 'status': 'RUNNING', 'url': title_element.get_attribute('href')})

                scroll_and_click(
                    driver,
                    title_element,
                )

                random_sleep(
                    config["timing"]["sleepMin"],
                    config["timing"]["sleepMax"],
                    stop_event,
                )

                session_logger.info(f"Video '{title}' opened successfully.", extra={'action': 'OPEN_VIDEO', 'status': 'SUCCESS', 'url': driver.current_url})
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

            session_logger.info("Reached end of search results.")
            return False

        last_height = new_height


def watch_video(driver, config, stop_event, session_logger, keyword=None):
    """
    Watch opened YouTube video for a random duration.
    """

    import random
    import time

    watch_time = random.randint(
        config["youtube"]["watchTimeMin"],
        config["youtube"]["watchTimeMax"],
    )

    session_logger.info(f"Watching video for {watch_time} seconds...", extra={'action': 'WATCH_VIDEO', 'status': 'RUNNING', 'duration_ms': watch_time * 1000, 'url': driver.current_url, 'keyword': keyword})
    start_time = time.time()

    while (time.time() - start_time) < watch_time:

        # Use wait instead of sleep to be responsive to stop_event
        wait_duration = min(watch_time - (time.time() - start_time), 1)
        if stop_event.wait(wait_duration):
            break

    session_logger.info("Finished watching video.", extra={'action': 'WATCH_VIDEO', 'status': 'SUCCESS', 'url': driver.current_url, 'duration_ms': (time.time() - start_time) * 1000, 'keyword': keyword})


def go_to_home(driver, config, stop_event, session_logger):
    """
    Return to YouTube home page by clicking the logo.
    """
    session_logger.info("Returning to YouTube home...", extra={'action': 'GO_HOME', 'status': 'RUNNING'})

    try:

        logo = wait_for_element(
            driver,
            YOUTUBE["youtubeLogo"],
        )

        scroll_and_click(  # This click might navigate away, so log URL before.
            driver,
            logo,
        )

        random_sleep(
            config["timing"]["sleepMin"],
            config["timing"]["sleepMax"],
            stop_event,
        )
        session_logger.info("Successfully returned to home page.", extra={'action': 'GO_HOME', 'status': 'SUCCESS', 'url': driver.current_url})
    except Exception as error:
        session_logger.warning(f"Failed to return to home page by clicking logo: {error}",
                               extra={'action': 'GO_HOME', 'status': 'FAILED', 'error_message': str(error), 'url': driver.current_url})


def close_mini_player(driver, session_logger=None):
    """
    Close YouTube mini player if it is open.
    """

    try:

        close_btn = driver.find_element(
            By.CSS_SELECTOR,
            "button.ytp-miniplayer-close-button"
        )

        close_btn.click()

        if session_logger:
            session_logger.info("Mini player closed.", extra={'action': 'MINIPLAYER_CLOSED', 'status': 'SUCCESS'})

    except Exception:
        pass