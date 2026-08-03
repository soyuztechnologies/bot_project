# SEO Search Automation Bot

This project is a Python browser automation bot that searches configured
keywords in multiple search engines, scans search result pages for a target
website domain, and opens the target website when it is found.

The project uses **SeleniumBase** with Google Chrome for browser automation.

---

# Project Overview

Main flow:

1. `main.py` loads `config.json`.
2. Keywords are loaded from `data/keywords.json`.
3. Search engine settings are loaded from `data/search_engines.json`.
4. Parallel browser sessions are started from `automation/session.py`.
5. Each session:
   - Opens a search engine.
   - Searches a keyword.
   - Scans search result links.
   - Opens the configured target website when found.

---

# Project Structure

```
bot_project/
│
├── automation/
│   ├── search_engine.py
│   ├── session.py
│   └── website.py
│
├── browser/
│   └── browser.py
│
├── data/
│   ├── keywords.json
│   └── search_engines.json
│
├── utils/
│   └── helpers.py
│
├── config.json
├── main.py
└── requirements.txt
```

---

# Requirements

Install the following before running:

- Python 3.10+
- Google Chrome
- Internet connection

Python dependencies:

- seleniumbase


---

# Setup

Go to project folder.

```powershell
cd "C:\path\to\bot_project"
```

Create virtual environment.

Windows

```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies.

```bash
pip install -r requirements.txt
```

If SeleniumBase is being installed for the first time, install the browser driver once:

```bash
seleniumbase install chromedriver
```

Usually SeleniumBase automatically downloads and manages compatible drivers.

---

# Configuration

Edit `config.json`.

Example:

```json
{
  "website": {
    "domain": "anubhavtrainings.com"
  },

  "search": {
    "engines": [
      "google",
      "bing",
      "duckduckgo",
      "yahoo"
    ],
    "maxPages": 20
  },

  "browser": {
    "mode": "headed",
    "maximize": true
  }
}
```

---

## Search Engines

Search engine definitions are stored in

```
data/search_engines.json
```

Every engine contains:

```json
{
    "url": "...",
    "searchUrl": "...",

    "searchBox": {
        "by": "NAME",
        "value": "q"
    },

    "resultLinks": {
        "by": "XPATH",
        "value": "..."
    },

    "nextButton": {
        "by": "CSS_SELECTOR",
        "value": "..."
    }
}
```

Supported locator types:

- ID
- NAME
- XPATH
- CSS_SELECTOR
- CLASS_NAME
- TAG_NAME

Adding a new search engine usually requires only updating
`search_engines.json`.

---

## Browser Modes

Headed mode

```json
"browser": {
    "mode": "headed"
}
```

Chrome opens normally.

Headless mode

```json
"browser": {
    "mode": "headless"
}
```

Chrome runs in the background without displaying a window.

---

# Keywords

Keywords are stored inside

```
data/keywords.json
```

Example

```json
[
    "sap ui5",
    "sap btp",
    "sap rap"
]
```

---

# Run

Activate virtual environment.

Run

```bash
python main.py
```

or

```powershell
.\.venv\Scripts\python.exe main.py
```

---

# Expected Output

```
==================================================
Automation Project Started
==================================================

Project Path      : ...
Search Engines    : google, bing, yahoo
Parallel Sessions : 2
Keywords          : 5

Starting session for:
sap ui5

Website found.

==================================================
Automation Completed
==================================================
```

If no matching domain is found,

```
Website not found.
```

---

# Adding a New Search Engine

To support another search engine:

1. Open

```
data/search_engines.json
```

2. Add:

- url
- searchUrl
- searchBox
- resultLinks
- nextButton (optional)

Example:

```json
"example": {

    "url":"https://example.com",

    "searchUrl":"https://example.com/search?q={query}",

    "searchBox":{

        "by":"NAME",

        "value":"q"

    },

    "resultLinks":{

        "by":"XPATH",

        "value":"//div[@class='result']//a"

    },

    "nextButton":{

        "by":"CSS_SELECTOR",

        "value":".next"

    }
}
```

Then simply add the engine name inside `config.json`.

No Python code changes are required if the engine follows the same configuration format.

---

# Troubleshooting

## ModuleNotFoundError

Reinstall packages.

```bash
pip install -r requirements.txt
```

---

## Browser does not open

Check:

- Chrome is installed.
- Virtual environment is activated.
- SeleniumBase is installed.

---

## Headless works but Headed does not

Possible reasons:

- Antivirus
- Chrome profile issues
- Search engine anti-bot detection
- Multiple parallel browser sessions

Try reducing:

```json
"sessions": {

    "parallel":1

}
```

---

## Search engine blocks requests

Some search engines (especially Google) may temporarily block automated traffic by showing CAPTCHA or verification pages.

If this happens:

- Wait a while before retrying.
- Reduce parallel sessions.
- Increase delays between searches.
- Use alternative search engines like Bing, Yahoo, or DuckDuckGo.

---

# Notes

- `.venv/` should not be committed.
- `.git/` should not be committed.
- Search results change over time.
- Different search engines use different HTML structures, so locator updates may occasionally be required.
- SeleniumBase automatically manages ChromeDriver versions for compatible Chrome installations.
