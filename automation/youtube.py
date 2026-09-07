"""
youtube.py
 
This module contains generic YouTube automation functions.
 
Responsibilities:
1. Open YouTube.
2. Search keyword.
3. Find target channel video.
4. Watch the opened video.
5. Support optional database/session logging.
"""
 
import json
import logging
import random
import time
 
from pathlib import Path
 
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
 
from automation.search_engine import (
    wait_for_element,
)
 
from utils.helpers import (
    human_typing,
    press_enter,
    random_sleep,
    scroll_and_click,
)
 
from utils.exceptions import (
    ConfigError,
    ConfigFileNotFoundError,
    ConfigInvalidError,
    YoutubeNetworkError,
    wrap_unexpected,
)
 
BASE_DIR = Path(__file__).resolve().parents[1]
 
logger = logging.getLogger(__name__)
 
 
# =========================================================
# YouTube Configuration
# =========================================================
 
 
def load_youtube_config():
    """
    Load YouTube configuration.
    Raises: ConfigFileNotFoundError, ConfigInvalidError (expected)
    """
    youtube_path = BASE_DIR / "data" / "youtube.json"
    if not youtube_path.exists():
        raise ConfigFileNotFoundError(f"YouTube config not found: {youtube_path}")
    try:
        with open(youtube_path, encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError as e:
        raise ConfigInvalidError(f"Invalid JSON in {youtube_path}: {e}", cause=e) from e
    except OSError as e:
        raise ConfigError(f"Failed to read {youtube_path}: {e}", cause=e) from e
    except Exception as e:
        raise wrap_unexpected(e, "load_youtube_config") from e
 
 
YOUTUBE = load_youtube_config()
 
 
# =========================================================
# Network Navigation Errors
# =========================================================
 
NETWORK_NAVIGATION_ERRORS = (
    "ERR_INTERNET_DISCONNECTED",
    "ERR_NETWORK_CHANGED",
    "ERR_NAME_NOT_RESOLVED",
    "ERR_CONNECTION_RESET",
    "ERR_CONNECTION_TIMED_OUT",
    "ERR_PROXY_CONNECTION_FAILED",
    "ERR_TUNNEL_CONNECTION_FAILED",
)
 
 
def _is_network_navigation_error(error):
    """
    Check whether a WebDriver exception was caused
    by a known network/navigation problem.
    """
 
    message = str(error)
 
    return "net::" in message and any(
        code in message for code in NETWORK_NAVIGATION_ERRORS
    )
 
 
# =========================================================
# Open YouTube
# =========================================================
 
 
def open_youtube(
    driver,
    config,
    stop_event=None,
    session_logger=None,
):
    """
    Open YouTube home page.
 
    Network navigation errors are retried according
    to youtube.retryCount and navigationRetryDelay.
    """
 
    retry_count = max(
        1,
        int(
            config.get("youtube", {}).get(
                "retryCount",
                3,
            )
        ),
    )
 
    retry_delay = max(
        1,
        int(
            config.get("youtube", {}).get(
                "navigationRetryDelay",
                10,
            )
        ),
    )
 
    for attempt in range(
        1,
        retry_count + 1,
    ):
 
        if stop_event and stop_event.is_set():
 
            return False
 
        if session_logger:
 
            session_logger.info(
                f"Opening YouTube: {YOUTUBE['url']}",
                extra={
                    "action": "YOUTUBE_OPEN",
                    "status": "RUNNING",
                    "url": YOUTUBE["url"],
                },
            )
 
        else:
 
            print("Opening YouTube...")
 
        try:
 
            driver.get(YOUTUBE["url"])
 
            random_sleep(
                config["timing"]["sleepMin"],
                config["timing"]["sleepMax"],
                stop_event,
            )
 
            if stop_event and stop_event.is_set():
 
                return False
 
            if session_logger:
 
                session_logger.info(
                    "YouTube home page opened.",
                    extra={
                        "action": "YOUTUBE_OPEN",
                        "status": "SUCCESS",
                        "url": driver.current_url,
                    },
                )
 
            else:
 
                print("YouTube opened successfully.")
 
            return True
 
        except WebDriverException as error:

            if not _is_network_navigation_error(error) or attempt == retry_count:
                raise YoutubeNetworkError(f"YouTube navigation failed: {error}", cause=error) from error
 
            if session_logger:
 
                session_logger.warning(
                    "YouTube navigation failed due "
                    "to a network error. "
                    f"Retrying in {retry_delay} seconds "
                    f"({attempt}/{retry_count}).",
                    extra={
                        "action": "YOUTUBE_OPEN",
                        "status": "RETRYING",
                        "url": YOUTUBE["url"],
                        "error_message": str(error),
                    },
                )
 
            else:
 
                print(
                    "YouTube navigation failed due "
                    "to network error. "
                    f"Retrying in {retry_delay} seconds "
                    f"({attempt}/{retry_count})."
                )
 
            if stop_event:
 
                if stop_event.wait(retry_delay):
 
                    return False
 
            else:
 
                time.sleep(retry_delay)
 
    return False
 
 
# =========================================================
# Search YouTube
# =========================================================
 
 
def search_video(
    driver,
    keyword,
    config,
    stop_event=None,
    session_logger=None,
):
    """
    Search keyword on YouTube.
    """
 
    if session_logger:
 
        session_logger.info(
            f"Searching for video with keyword: " f"'{keyword}'",
            extra={
                "action": "VIDEO_SEARCH_STARTED",
                "status": "RUNNING",
            },
        )
 
    search_box = wait_for_element(
        driver,
        YOUTUBE["searchBox"],
    )
 
    search_box.click()
 
    # -----------------------------------------------------
    # Preserve File-1 clearing behaviour
    # -----------------------------------------------------
 
    search_box.send_keys(
        Keys.CONTROL,
        "a",
    )
 
    random_sleep(
        0.2,
        0.4,
        stop_event,
    )
 
    search_box.send_keys(Keys.DELETE)
 
    random_sleep(
        0.2,
        0.4,
        stop_event,
    )
 
    human_typing(
        search_box,
        keyword,
        config["timing"]["typingMin"],
        config["timing"]["typingMax"],
        stop_event,
    )
 
    if stop_event and stop_event.is_set():
 
        return False
 
    press_enter(search_box)
 
    random_sleep(
        config["timing"]["sleepMin"],
        config["timing"]["sleepMax"],
        stop_event,
    )
 
    if session_logger:
 
        session_logger.info(
            f"Video search for '{keyword}' initiated.",
            extra={
                "action": "VIDEO_SEARCH_STARTED",
                "status": "SUCCESS",
            },
        )
 
    return True
 
 
# =========================================================
# Get Video Cards
# =========================================================
 
 
def get_video_cards(
    driver,
    stop_event=None,
):
    """
    Return all visible YouTube search results
    (videos + courses).
    """
 
    if stop_event and stop_event.is_set():
 
        return []
 
    try:
 
        video_cards = driver.find_elements(
            By.CSS_SELECTOR,
            "ytd-video-renderer",
        )
 
        if stop_event and stop_event.is_set():
 
            return []
 
        course_cards = driver.find_elements(
            By.CSS_SELECTOR,
            "yt-lockup-view-model",
        )
 
        return video_cards + course_cards
 
    except Exception:
 
        return []
 
 
# =========================================================
# Get Video Title
# =========================================================
 
 
def get_video_title(result):
    """
    Return title element and text for both
    videos and courses.
    """

    if result.tag_name == "ytd-video-renderer":

        title = result.find_element(
            By.CSS_SELECTOR,
            "#video-title",
        )

        return (
            title,
            (title.text or "").strip(),
        )

    elif result.tag_name == "yt-lockup-view-model":

        title = result.find_element(
            By.CSS_SELECTOR,
            ".ytLockupMetadataViewModelTitle",
        )

        return (
            title,
            (title.text or "").strip(),
        )

    raise ValueError(f"Unsupported result type: {getattr(result, 'tag_name', None)}")
 
 
# =========================================================
# Get Channel Name
# =========================================================
 
 
def get_channel_name(result):
    """
    Return channel name for videos and courses.
    """
 
    if result.tag_name == "ytd-video-renderer":
 
        try:
 
            return result.find_element(
                "css selector",
                "#channel-name a",
            ).text.strip()
 
        except Exception:
 
            return ""
 
    elif result.tag_name == "yt-lockup-view-model":
 
        try:
 
            return result.find_element(
                "css selector",
                "a[href^='/@']",
            ).text.strip()
 
        except Exception:
 
            return ""
 
    return ""
 
 
# =========================================================
# Find Target Video
# =========================================================
 
 
def find_target_video(
    driver,
    config,
    stop_event=None,
    session_logger=None,
):
    """
    Find the first video/course uploaded
    by the target channel.
    """
 
    target_channel = config["youtube"]["targetChannel"]
 
    if session_logger:
 
        session_logger.info(
            f"Scanning results for target channel: " f"'{target_channel}'",
            extra={
                "action": "SCAN_FOR_CHANNEL",
                "status": "RUNNING",
            },
        )
 
    checked = set()

    last_height = 0

    try:
        max_scrolls = int(config.get("youtube", {}).get("maxScrolls", 20))
    except Exception:
        max_scrolls = 20
    max_scrolls = max(1, max_scrolls)
    scrolls_done = 0

    while scrolls_done < max_scrolls:

        if stop_event and stop_event.is_set():

            return False

        videos = get_video_cards(
            driver,
            stop_event,
        )

        if not videos:

            if session_logger:

                session_logger.warning("No video cards found on the page.")

            return False

        # -------------------------------------------------
        # Check visible results (single snapshot per page to
        # avoid O(n^2) re-fetching; stale items are skipped)
        # -------------------------------------------------

        for index in range(len(videos)):

            if stop_event and stop_event.is_set():

                return False

            if index >= len(videos):

                break

            video = videos[index]
 
            try:
 
                channel = get_channel_name(video)
 
                title_element, title = get_video_title(video)
 
            except Exception:

                continue

            try:
                if not (title or "").strip() or not (channel or "").strip():
                    continue
            except Exception:
                continue
 
            key = f"{title}|{channel}"
 
            if key in checked:
 
                continue
 
            checked.add(key)
 
            # -------------------------------------------------
            # Logging / Console Output
            # -------------------------------------------------
 
            if session_logger:
 
                session_logger.debug(f"Checking video: " f"'{title}' by '{channel}'")
 
            else:
 
                print(f"Checking : {title}")
 
                print(f"Channel  : {channel}")
 
            random_sleep(
                0.4,
                0.8,
                stop_event,
            )
 
            # -------------------------------------------------
            # Target Channel Found
            # -------------------------------------------------
 
            if target_channel.lower() in channel.lower():
 
                if not session_logger:
 
                    print(f"\nTarget channel found : " f"{channel}")
 
                random_sleep(
                    1,
                    2,
                    stop_event,
                )
 
                if session_logger:
 
                    session_logger.info(f"Target channel video found: " f"'{title}'")
 
                else:
 
                    print(f"Opening : {title}")
 
                if session_logger:
 
                    try:
 
                        video_url = title_element.get_attribute("href")
 
                    except Exception:
 
                        video_url = None
 
                    session_logger.info(
                        f"Opening video: {title}",
                        extra={
                            "action": "OPEN_VIDEO",
                            "status": "RUNNING",
                            "url": video_url,
                        },
                    )
 
                scroll_and_click(
                    driver,
                    title_element,
                    stop_event,
                )
 
                if stop_event and stop_event.is_set():
 
                    return False
 
                random_sleep(
                    config["timing"]["sleepMin"],
                    config["timing"]["sleepMax"],
                    stop_event,
                )
 
                if session_logger:
 
                    session_logger.info(
                        f"Video '{title}' " f"opened successfully.",
                        extra={
                            "action": "OPEN_VIDEO",
                            "status": "SUCCESS",
                            "url": driver.current_url,
                        },
                    )
 
                return True
 
            # -------------------------------------------------
            # Small Scroll
            # -------------------------------------------------
 
            if (index + 1) % 3 == 0:
 
                driver.execute_script("window.scrollBy(0, 350);")
 
                random_sleep(
                    0.5,
                    1,
                    stop_event,
                )
 
        # -----------------------------------------------------
        # Move to next screen
        # -----------------------------------------------------
 
        driver.execute_script("window.scrollBy(0, window.innerHeight);")

        random_sleep(
            config["timing"]["sleepMin"],
            config["timing"]["sleepMax"],
            stop_event,
        )

        if stop_event and stop_event.is_set():

            return False

        scrolls_done += 1

        try:
            new_height = driver.execute_script(
                "return document.documentElement.scrollHeight"
            )
        except Exception:
            return False

        if new_height == last_height:

            if session_logger:

                session_logger.info("Reached end of search results.")

            else:

                print("\nReached end of search results.")

            return False

        last_height = new_height

    if session_logger:
        session_logger.info(f"Reached max scrolls ({max_scrolls}), stopping scan.")
    else:
        print(f"\nReached max scrolls ({max_scrolls}).")

    return False
 
 
def _set_video_quality_144p(
    driver,
    stop_event=None,
    session_logger=None,
):
    """
    Try to set YouTube playback quality to 144p.
 
    Uses the YouTube player API first and falls back to
    the YouTube Quality menu if required.
 
    If 144p is unavailable, the video continues normally.
    """
 
    try:
 
        if stop_event and stop_event.is_set():
            return False
 
        # -------------------------------------------------
        # Give YouTube player a moment to initialize
        # -------------------------------------------------
 
        WebDriverWait(
            driver,
            8,
        ).until(
            lambda d: d.execute_script(
                """
                const player =
                    document.getElementById("movie_player");
 
                return player &&
                       typeof player.setPlaybackQuality === "function";
                """
            )
        )
 
        # -------------------------------------------------
        # Try YouTube internal player API
        # -------------------------------------------------
 
        result = driver.execute_script(
            """
            const player =
                document.getElementById("movie_player");
 
            if (!player) {
                return {
                    success: false,
                    reason: "player_not_found"
                };
            }
 
            if (
                typeof player.getAvailableQualityLevels ===
                "function"
            ) {
                const levels =
                    player.getAvailableQualityLevels();
 
                if (
                    Array.isArray(levels) &&
                    levels.length > 0 &&
                    !levels.includes("tiny")
                ) {
                    return {
                        success: false,
                        reason: "144p_unavailable",
                        levels: levels
                    };
                }
            }
 
            if (
                typeof player.setPlaybackQualityRange ===
                "function"
            ) {
                try {
                    player.setPlaybackQualityRange(
                        "tiny",
                        "tiny"
                    );
                } catch (e) {}
            }
 
            if (
                typeof player.setPlaybackQuality ===
                "function"
            ) {
                player.setPlaybackQuality("tiny");
            }
 
            let quality = null;
 
            if (
                typeof player.getPlaybackQuality ===
                "function"
            ) {
                quality = player.getPlaybackQuality();
            }
 
            return {
                success: quality === "tiny",
                quality: quality
            };
            """
        )
 
        # -------------------------------------------------
        # Verify API result
        # -------------------------------------------------
 
        if result and result.get("success"):
 
            if session_logger:
 
                session_logger.info(
                    "Video quality set to 144p using player API.",
                    extra={
                        "action": "SET_VIDEO_QUALITY",
                        "status": "SUCCESS",
                    },
                )
 
            else:
 
                print(
                    "Video quality set to 144p."
                )
 
            return True
 
        # -------------------------------------------------
        # 144p unavailable
        # -------------------------------------------------
 
        if (
            result
            and result.get("reason") == "144p_unavailable"
        ):
 
            if session_logger:
 
                session_logger.info(
                    "144p is not available for this video.",
                    extra={
                        "action": "SET_VIDEO_QUALITY",
                        "status": "UNAVAILABLE",
                    },
                )
 
            else:
 
                print(
                    "144p is not available for this video."
                )
 
            return False
 
    except Exception as error:
 
        if session_logger:
 
            session_logger.warning(
                f"Player API quality selection failed: {error}",
                extra={
                    "action": "SET_VIDEO_QUALITY",
                    "status": "API_FAILED",
                    "error_message": str(error),
                },
            )
 
        else:
 
            print(
                f"Player API quality selection failed: {error}"
            )
 
    # -----------------------------------------------------
    # UI fallback
    # -----------------------------------------------------
 
    try:
 
        if stop_event and stop_event.is_set():
            return False
 
        settings_button = WebDriverWait(
            driver,
            5,
        ).until(
            EC.element_to_be_clickable(
                (
                    By.CSS_SELECTOR,
                    ".ytp-settings-button",
                )
            )
        )
 
        driver.execute_script(
            "arguments[0].click();",
            settings_button,
        )

        if stop_event:
            stop_event.wait(0.5)
        else:
            time.sleep(0.5)

        # Find Quality menu item
        quality_item = None
 
        for item in driver.find_elements(
            By.CSS_SELECTOR,
            ".ytp-menuitem",
        ):
 
            try:
 
                text = item.text.strip().lower()
 
                if text == "quality" or text.startswith(
                    "quality"
                ):
 
                    quality_item = item
                    break
 
            except Exception:
                continue
 
        if quality_item is None:
 
            return False
 
        driver.execute_script(
            "arguments[0].click();",
            quality_item,
        )

        if stop_event:
            stop_event.wait(0.5)
        else:
            time.sleep(0.5)

        # Find 144p option
        option_144p = None
 
        for option in driver.find_elements(
            By.CSS_SELECTOR,
            ".ytp-menuitem",
        ):
 
            try:
 
                text = option.text.strip().lower()
 
                if text.startswith("144p"):
 
                    option_144p = option
                    break
 
            except Exception:
                continue
 
        if option_144p is None:
 
            return False
 
        driver.execute_script(
            "arguments[0].click();",
            option_144p,
        )

        if stop_event:
            stop_event.wait(0.5)
        else:
            time.sleep(0.5)
 
        if session_logger:
 
            session_logger.info(
                "Video quality selected as 144p using UI fallback.",
                extra={
                    "action": "SET_VIDEO_QUALITY",
                    "status": "SUCCESS",
                },
            )
 
        else:
 
            print(
                "Video quality selected: 144p."
            )
 
        return True
 
    except Exception as error:
 
        if session_logger:
 
            session_logger.warning(
                f"Could not set video quality to 144p: {error}",
                extra={
                    "action": "SET_VIDEO_QUALITY",
                    "status": "FAILED",
                    "error_message": str(error),
                },
            )
 
        else:
 
            print(
                f"Could not set video quality to 144p: {error}"
            )
 
        return False
 
 
# =========================================================
# Watch Video
# =========================================================
 
 
def watch_video(
    driver,
    config,
    stop_event=None,
    session_logger=None,
    keyword=None,
):
    """
    Watch opened YouTube video for a random duration.
 
    Video audio is muted for all supported browsers.
    """
 
    # -----------------------------------------------------
    # Mute YouTube Video
    # -----------------------------------------------------
 
    try:
 
        video = driver.find_element(
            By.TAG_NAME,
            "video",
        )
 
        driver.execute_script(
            """
            arguments[0].muted = true;
            arguments[0].volume = 0;
            """,
            video,
        )
 
        if not session_logger:
 
            print("Video audio muted.")
 
    except Exception as error:
 
        if session_logger:
 
            session_logger.warning(
                f"Failed to mute video: {error}",
                extra={
                    "action": "MUTE_VIDEO",
                    "status": "FAILED",
                    "error_message": str(error),
                },
            )
 
        else:
 
            print(f"Failed to mute video : {error}")
 
 
     # -----------------------------------------------------
    # Set YouTube Video Quality to 144p
    # -----------------------------------------------------
 
    _set_video_quality_144p(
        driver,
        stop_event,
        session_logger,
    )
 
    # -----------------------------------------------------
    # Random Watch Time
    # -----------------------------------------------------
 
    watch_time = random.randint(
        config["youtube"]["watchTimeMin"],
        config["youtube"]["watchTimeMax"],
    )
 
    if session_logger:
 
        session_logger.info(
            f"Watching video for " f"{watch_time} seconds...",
            extra={
                "action": "WATCH_VIDEO",
                "status": "RUNNING",
                "url": driver.current_url,
                "keyword": keyword,
            },
        )
 
    else:
 
        print(f"\nWatching video for " f"{watch_time} seconds...")
 
    start_time = time.time()
 
    while (time.time() - start_time) < watch_time:
 
        if stop_event and stop_event.is_set():
 
            return 0
 
        remaining = watch_time - (time.time() - start_time)
 
        if stop_event:
 
            stop_event.wait(
                min(
                    remaining,
                    1,
                )
            )
 
        else:
 
            time.sleep(
                min(
                    remaining,
                    1,
                )
            )
 
    if session_logger:
 
        session_logger.info(
            "Finished watching video.",
            extra={
                "action": "WATCH_VIDEO",
                "status": "SUCCESS",
                "url": driver.current_url,
                "keyword": keyword,
            },
        )
 
    else:
 
        print("Finished watching video.")
 
        print("Returning to YouTube home...")
 
    return watch_time
 
 
# =========================================================
# Go To YouTube Home
# =========================================================
 
 
def go_to_home(
    driver,
    config,
    stop_event=None,
    session_logger=None,
):
    """
    Return to YouTube home page by clicking the logo.
    """
 
    if session_logger:
 
        session_logger.info(
            "Returning to YouTube home...",
            extra={
                "action": "GO_HOME",
                "status": "RUNNING",
            },
        )
 
    else:
 
        print("Returning to YouTube home...")
 
    try:
 
        logo = wait_for_element(
            driver,
            YOUTUBE["youtubeLogo"],
        )
 
        if not session_logger:
 
            print("YouTube logo Found.")
 
        scroll_and_click(
            driver,
            logo,
        )
 
        if not session_logger:
 
            print("YouTube logo clicked.")
 
        random_sleep(
            config["timing"]["sleepMin"],
            config["timing"]["sleepMax"],
            stop_event,
        )
 
        if session_logger:
 
            session_logger.info(
                "Successfully returned to home page.",
                extra={
                    "action": "GO_HOME",
                    "status": "SUCCESS",
                    "url": driver.current_url,
                },
            )
 
    except Exception as error:
 
        if session_logger:
 
            session_logger.warning(
                f"Failed to return to home page " f"by clicking logo: {error}",
                extra={
                    "action": "GO_HOME",
                    "status": "FAILED",
                    "error_message": str(error),
                    "url": driver.current_url,
                },
            )
 
        else:
 
            print(f"Failed to return to home page : " f"{error}")
 
 
# =========================================================
# Close Mini Player
# =========================================================
 
 
def close_mini_player(
    driver,
    session_logger=None,
):
    """
    Close YouTube mini player if it is open.
    """
 
    try:
 
        close_btn = driver.find_element(
            By.CSS_SELECTOR,
            "button.ytp-miniplayer-close-button",
        )
 
        close_btn.click()
 
        if session_logger:
 
            session_logger.info(
                "Mini player closed.",
                extra={
                    "action": "MINIPLAYER_CLOSED",
                    "status": "SUCCESS",
                },
            )
 
        else:
 
            print("Mini player closed.")
 
    except Exception:

        pass