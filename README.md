# SEO & YouTube Automation Bot

A Python-based browser automation framework built using **SeleniumBase** for automating both **Search Engine** and **YouTube** workflows.

The framework is configuration-driven, supports parallel browser sessions, human-like interactions, and can be executed either locally or through Docker.

---

# Features

## Search Engine Automation

- Google
- Bing
- Yahoo
- DuckDuckGo
- Keyword-based searching
- Target website detection
- Website visit automation
- Internal page navigation
- Parallel browser sessions
- Human-like typing and scrolling
- Configurable search engines

---

## YouTube Automation

- Search videos using keywords
- Find videos from the configured target channel
- Support for videos and YouTube courses
- Watch videos for random durations
- Automatically return to YouTube Home
- Close Mini Player automatically
- Retry failed operations
- Parallel browser sessions
- Human-like scrolling and interaction

---

## General Features

- Configuration-driven architecture
- Multi-threaded browser sessions
- JSON-based configuration
- Docker support
- Interactive launcher
- Automatic logging
- Modular project structure

---

# Project Structure

```text
bot_project/
│
├── automation/
│   ├── search_engine.py
│   ├── session.py
│   ├── website.py
│   ├── youtube.py
│   └── youtube_session.py
│
├── browser/
│   └── browser.py
│
├── data/
│   ├── keywords.json
│   ├── search_engines.json
│   └── youtube.json
│
├── utils/
│   ├── helpers.py
│   └── logger.py
│
├── launcher.py
├── main.py
├── youtube_main.py
├── config.json
├── Dockerfile
├── .dockerignore
├── requirements.txt
└── README.md
```

---

# Requirements

- Python 3.10+
- Google Chrome
- Internet Connection

Install Python packages:

```bash
pip install -r requirements.txt
```

Install ChromeDriver (only once if required):

```bash
seleniumbase install chromedriver
```

---

# Local Setup

Clone the repository

```bash
git clone <repository-url>
cd bot_project
```

### Create Virtual Environment

#### Windows

```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

#### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies

```bash
pip install -r requirements.txt
```

---

# Running the Project (Without Docker)

## Website Automation

```bash
python main.py
```

## YouTube Automation

```bash
python youtube_main.py
```

---

# Docker Setup

The project supports both Website Automation and YouTube Automation using a **single Docker image**.

## Build Docker Image

```bash
docker build -t seo-bot .
```

## Run Docker Container

```bash
docker run -it --rm seo-bot
```

After starting the container, an interactive launcher will be displayed.

```text
==================================================
            SEO AUTOMATION BOT
==================================================

1. Website Automation
2. YouTube Automation

Enter your choice:
```

Choose the required automation and it will start automatically.

---

# Configuration

The framework is completely configuration-driven.

## config.json

Contains:

- Browser configuration
- Parallel session settings
- Search engine configuration
- Website configuration
- YouTube configuration
- Timing configuration

---

## search_engines.json

Contains:

- Search engine URLs
- Search box locators
- Result locators
- Next page locators

---

## youtube.json

Contains:

- YouTube URL
- Target channel
- Search box locator
- Video locator
- Channel locator
- Logo locator

---

## keywords.json

Contains the list of keywords used during automation.

---

# Automation Workflow

## Website Automation

```text
Load Configuration
        │
        ▼
Load Keywords
        │
        ▼
Open Search Engine
        │
        ▼
Search Keyword
        │
        ▼
Find Target Website
        │
        ▼
Visit Website
        │
        ▼
Visit Internal Links
        │
        ▼
Close Browser
```

---

## YouTube Automation

```text
Load Configuration
        │
        ▼
Load Keywords
        │
        ▼
Open Search Engine
        │
        ▼
Search Keyword
        │
        ▼
Open YouTube Result
        │
        ▼
Find Target Channel Video
        │
        ▼
Watch Video
        │
        ▼
Return to Home
```

---

# Parallel Sessions

The number of browser sessions is configurable.

Example:

```json
"sessions": {
    "parallel": 4
}
```

Each browser runs independently in its own thread.

---

# Configuration Files

| File | Purpose |
|------|---------|
| config.json | Global project configuration |
| keywords.json | Search keywords |
| search_engines.json | Search engine configuration |
| youtube.json | YouTube automation configuration |

---

# Technologies Used

- Python
- SeleniumBase
- Selenium WebDriver
- Google Chrome
- Threading
- JSON
- Docker

---

# Future Enhancements

- Human-like mouse movement
- Random video interactions
- Recommended video navigation
- Additional browser support
- Improved anti-detection behaviour
- Enhanced activity logging
- Docker Compose support
- Task Scheduler / Cron integration

---

# Notes

- Do not commit the `.venv/` directory.
- Do not commit browser cache or temporary files.
- Search engine and YouTube page structures may change over time.
- Update element locators whenever required.
- SeleniumBase automatically manages the compatible ChromeDriver version.