"""
browser_selector.py

Selects which browser should be used for a session.
"""

import random


def select_browser(config):
    """
    Select a browser based on the configured distribution.

    Args:
        config (dict): Project configuration.

    Returns:
        str: Browser name.
    """

    distribution = config["browser"].get("distribution")

    # Backward compatibility
    if not distribution:
        browsers = config["browser"].get("browsers", ["chrome"])
        return random.choice(browsers)

    browser_names = list(distribution.keys())
    browser_weights = list(distribution.values())

    return random.choices(
        browser_names,
        weights=browser_weights,
        k=1
    )[0]