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
 
    browser_cfg = config.get("browser", {}) if isinstance(config, dict) else {}
    distribution = browser_cfg.get("distribution")

    # Backward compatibility
    if not distribution:
        browsers = browser_cfg.get("browsers", ["chrome"]) or ["chrome"]
        return str(random.choice(browsers)).strip().lower()

    # Filter zero-weight entries to avoid selecting disabled browsers
    try:
        filtered = [(str(k).strip().lower(), v) for k, v in distribution.items() if float(v) > 0]
    except Exception:
        filtered = []
    if not filtered:
        # Fallback to browsers list if distribution has no positive weights
        browsers = browser_cfg.get("browsers", ["chrome"]) or ["chrome"]
        return str(random.choice(browsers)).strip().lower() if browsers else "chrome"
    browser_names, browser_weights = zip(*filtered)
    browser_names = list(browser_names)
    browser_weights = list(browser_weights)
 
    return random.choices(
        browser_names,
        weights=browser_weights,
        k=1
    )[0]