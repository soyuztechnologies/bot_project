"""
website.py

Actions to perform after the target website has been opened from search
results.
"""

from utils.helpers import random_sleep, simulate_human_reading


def visit_website(driver, config: dict, stop_event=None) -> None:
    """
    Simulate a short, human-like visit on the target website.

    Args:
        driver: Selenium WebDriver.
        config (dict): Project configuration.
    """

    timing = config["timing"]

    random_sleep(timing["sleepMin"], timing["sleepMax"], stop_event)

    for _ in range(2):
        if stop_event and stop_event.is_set():
            return

        simulate_human_reading(driver, stop_event)

    random_sleep(timing["scrollMin"], timing["scrollMax"], stop_event)
