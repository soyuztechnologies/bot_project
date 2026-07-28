# SEO Search Automation Bot

This project is a Python browser automation bot that searches configured
keywords in a search engine, scans result pages for a target website domain, and
opens the target website when it is found.

The project currently uses Selenium with `undetected-chromedriver` and Google
Chrome.

## Project Overview

Main flow:

1. `main.py` loads `config.json`.
2. Keywords are loaded from `data/keywords.json`.
3. Search engine selectors are loaded from `data/search_engines.json`.
4. Parallel browser sessions are started from `automation/session.py`.
5. Each session opens the selected search engine, searches a keyword, scans
   result links, and visits the configured target website if found.

Important folders:

- `automation/` contains search, session, and website visit workflows.
- `browser/` contains Chrome browser setup and ChromeDriver handling.
- `data/` contains keywords and search engine locator settings.
- `utils/` contains shared helper functions such as typing, scrolling, and
  sleeps.


## Requirements

Install these before running the project:

- Python 3.10 or newer
- Google Chrome
- Internet connection

Python packages are listed in `requirements.txt`:

- `selenium`
- `undetected-chromedriver`
- `setuptools`

## Setup

Open a terminal in the project folder:

```powershell
cd "C:\path\to\bot_project"
```

Create a virtual environment.

Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## Configuration

Edit `config.json` before running.

Target website:

```json
"website": {
  "domain": "anubhavtrainings.com"
}
```

Search settings:

```json
"search": {
  "engines": ["google", "bing", "duckduckgo", "yahoo"],
  "maxPages": 20
}
```

Each browser session rotates through the configured engines. For example, with
`["google", "bing"]`, parallel sessions alternate between Google and Bing.

To run every search engine defined in `data/search_engines.json`, use:

```json
"search": {
  "engines": "all",
  "maxPages": 20
}
```

To use only one search engine:

```json
"search": {
  "engines": ["google"],
  "maxPages": 20
}
```

Browser settings:

```json
"browser": {
  "name": "chrome",
  "mode": "headed",
  "maximize": true
}
```

Use `"mode": "headless"` if you want Chrome to run without a visible browser
window.

Keywords are stored in `data/keywords.json`:

```json
[
  "sap ui5",
  "sap btp"
]
```

Search engine locator settings are stored in `data/search_engines.json`. You can
add more engines there without changing Python code, then add the engine name to
`config.json`.

Each search engine entry supports:

```json
"engine_name": {
  "url": "https://example.com",
  "searchUrl": "https://example.com/search?q={query}",
  "openTarget": "direct",
  "searchBox": {
    "by": "NAME",
    "value": "q"
  },
  "nextButton": {
    "by": "CSS_SELECTOR",
    "value": ".next"
  },
  "resultLinks": {
    "by": "XPATH",
    "value": "//a[@href]"
  }
}
```

`searchUrl` is recommended because it lets the bot open the results page
directly. `nextButton` is optional; without it, the bot scans only the first
results page. `openTarget` can be `"direct"` or `"click"`. Direct mode is more
stable during parallel runs because it resolves the matched result URL and opens
it directly.

## Run The Project

Make sure the virtual environment is activated, then run:

```bash
python main.py
```

On Windows, you can also run without activating:

```powershell
.\.venv\Scripts\python.exe main.py
```

Expected output looks like:

```text
==================================================
Automation Project Started
==================================================
Project Path      : ...
Search Engines    : google, bing, duckduckgo, yahoo
Parallel Sessions : 4
Keywords          : 2
Starting session for: sap ui5
Starting session for: sap btp
Website found.
==================================================
Automation Completed
==================================================
```

If the configured domain is not present in the scanned search results, the bot
will print:

```text
Website not found.
```

## Troubleshooting

If Python is not found, install Python and make sure it is added to your system
PATH.

If ChromeDriver fails because of a version mismatch, update Google Chrome and
run the project again. The project automatically detects the installed Chrome
major version on Windows.

If dependencies are missing, reinstall them:

```bash
pip install -r requirements.txt
```

If a browser opens but pages do not load, check your internet connection,
firewall, proxy, or antivirus settings.

If many browser windows open, reduce parallel sessions in `config.json`:

```json
"sessions": {
  "parallel": 1,
  "iterations": 1
}
```

## Notes

- `.venv/` and `.drivers/` are local machine folders and should not be committed.
- Search results change over time, so a keyword may not always find the target
  domain.
- Large parallel values can trigger search engine rate limits or system resource
  issues. Start with `parallel: 1` or `parallel: 2` if testing on a new computer.
