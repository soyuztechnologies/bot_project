import random


def select_search_engine(config):
    from utils.exceptions import EngineConfigError

    search_cfg = config.get("search", {}) if isinstance(config, dict) else {}
    engines = search_cfg.get("engines", [])

    if not engines:
        raise EngineConfigError("No search engines configured.")

    selected_engine = random.choice(engines)

    return str(selected_engine).strip().lower()