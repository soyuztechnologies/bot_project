import random


def select_search_engine(config):
    from utils.exceptions import EngineConfigError

    search_cfg = config.get("search", {}) if isinstance(config, dict) else {}
    engines = search_cfg.get("engines", [])

    if not engines:
        raise EngineConfigError("No search engines configured.")

    selected_engine = random.choice(engines)

    return str(selected_engine).strip().lower()


def filter_engines_for_browser(engine_names, search_engines, browser):
    """
    Return engine names compatible with the given browser.

    DuckDuckGo is blocked by DDG's bot protection (Anomaly + duck image
    challenge) only on some browsers. Empirically tested:
    - works: chrome, firefox, opera
    - blocked: edge, brave (DDG serves the image challenge / empty page)
    """
    browser = (browser or "").lower()

    # DDG is NOT attempted on these browsers.
    DDG_BLOCKED_BROWSERS = {"edge", "brave"}

    if not engine_names:
        return []

    allowed = []
    for name in engine_names:
        engine_cfg = None
        if isinstance(search_engines, dict):
            engine_cfg = search_engines.get(name)
        is_ddg = False
        if isinstance(engine_cfg, dict):
            is_ddg = bool(engine_cfg.get("isDuckDuckGo"))
        elif str(name).strip().lower() == "duckduckgo":
            is_ddg = True

        if is_ddg and browser in DDG_BLOCKED_BROWSERS:
            continue

        allowed.append(name)

    return allowed