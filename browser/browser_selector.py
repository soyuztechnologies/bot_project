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
 
    # Filter zero-weight entries to avoid selecting disabled browsers
    filtered = [(k, v) for k, v in distribution.items() if float(v) > 0]
    if not filtered:
        # Fallback to browsers list if distribution has no positive weights
        browsers = config["browser"].get("browsers", ["chrome"])
        return random.choice(browsers) if browsers else "chrome"
    browser_names, browser_weights = zip(*filtered)
    browser_names = list(browser_names)
    browser_weights = list(browser_weights)
 
    return random.choices(
        browser_names,
        weights=browser_weights,
        k=1
    )[0]