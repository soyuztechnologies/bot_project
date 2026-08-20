import random


def select_search_engine(config):
    engines = config["search"].get("engines", [])

    if not engines:
        raise ValueError("No search engines configured.")

    selected_engine = random.choice(engines)

    return selected_engine.lower()