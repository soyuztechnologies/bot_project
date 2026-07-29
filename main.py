"""
main.py

Project Entry Point

Responsibilities:
1. Load configuration files.
2. Load keywords
3. Load search engine settings.
"""

import json
from pathlib import Path
from automation.session import start_parallel_sessions

BASE_DIR = Path(__file__).resolve().parent


def load_json(file_path):
    """
    Load and return JSON data.

    Args:
        file_path: Path object or string.

    Returns:
        dict | list
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"Required file not found: {file_path}")

    with file_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def project_path(relative_path):
    """Resolve a config path relative to this project folder."""

    return BASE_DIR / relative_path


def validate_config(config, keywords, search_engines):
    """Fail early with clear messages for missing or invalid config values."""

    required_sections = ["browser", "sessions", "search", "website", "timing", "files"]
    missing_sections = [
        section for section in required_sections if section not in config
    ]

    if missing_sections:
        raise KeyError(f"Missing config section(s): {', '.join(missing_sections)}")

    if not isinstance(keywords, list) or not keywords:
        raise ValueError("data/keywords.json must contain at least one keyword.")

    engine_names = get_search_engine_names(config, search_engines)

    if not engine_names:
        raise ValueError("Configure at least one search engine in search.engines.")

    missing_engines = [
        engine_name for engine_name in engine_names if engine_name not in search_engines
    ]

    if missing_engines:
        available = ", ".join(sorted(search_engines))
        raise KeyError(
            "Search engine(s) not configured: "
            f"{', '.join(missing_engines)}. Available: {available}"
        )

    for engine_name in engine_names:
        validate_search_engine(engine_name, search_engines[engine_name])

    parallel_sessions = int(config["sessions"].get("parallel", 1))

    if parallel_sessions < 1:
        raise ValueError("sessions.parallel must be 1 or greater.")

    max_pages = int(config["search"].get("maxPages", 1))

    if max_pages < 1:
        raise ValueError("search.maxPages must be 1 or greater.")


def validate_search_engine(engine_name, engine):
    """Validate one data/search_engines.json entry."""

    if "url" not in engine:
        raise KeyError(f"Search engine '{engine_name}' is missing 'url'.")

    if "resultLinks" not in engine:
        raise KeyError(f"Search engine '{engine_name}' is missing 'resultLinks'.")

    if "searchUrl" not in engine and "searchBox" not in engine:
        raise KeyError(
            f"Search engine '{engine_name}' needs either 'searchUrl' or 'searchBox'."
        )

    for locator_name in ("searchBox", "nextButton", "resultLinks"):
        locator = engine.get(locator_name)

        if not locator:
            continue

        if "by" not in locator or "value" not in locator:
            raise KeyError(
                f"Search engine '{engine_name}' locator '{locator_name}' "
                "must include 'by' and 'value'."
            )


def get_search_engine_names(config, search_engines):
    """Return the configured search engines to rotate across sessions."""

    configured_engines = config["search"].get("engines")

    if configured_engines:
        if isinstance(configured_engines, str):
            if configured_engines.lower() == "all":
                return list(search_engines.keys())

            return [configured_engines]

        engine_names = list(configured_engines)

        if any(str(engine_name).lower() == "all" for engine_name in engine_names):
            return list(search_engines.keys())

        return engine_names

    engine_name = config["search"].get("engine")

    if engine_name:
        return [engine_name]

    return list(search_engines.keys())


def main():
    print("=" * 50)
    print("Automation Project Started")
    print("=" * 50)

    # Load main config
    config = load_json(BASE_DIR / "config.json")

    # Load project data
    keywords = load_json(project_path(config["files"]["keywords"]))
    search_engines = load_json(project_path(config["files"]["searchEngines"]))

    validate_config(config, keywords, search_engines)

    engine_names = get_search_engine_names(config, search_engines)

    print(f"Project Path      : {BASE_DIR}")
    print(f"Search Engines    : {', '.join(engine_names)}")
    print(f"Parallel Sessions : {config['sessions']['parallel']}")
    print(f"Keywords          : {len(keywords)}")

    # Start automation
    stats = start_parallel_sessions(
        keywords,
        config,
        search_engines,
        engine_names,
    )

    print("=" * 50)
    print("Automation Completed")
    print("=" * 50)

    print(f"Total Sessions : {stats['total']}")
    print(f"Success        : {stats['success']}")
    print(f"Failed         : {stats['failed']}")
    print(f"Success Rate   : {stats['success_rate']}%")


if __name__ == "__main__":
    main()
