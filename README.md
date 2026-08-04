# SEO & YouTube Automation Bot
 
A Python-based browser automation framework built using **SeleniumBase** for automating both Search Engine and YouTube workflows.
 
The project is configuration-driven and supports multiple browser sessions running in parallel with human-like interactions.
 
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
- Configurable search engines
- Human-like typing and scrolling
 
---
 
## YouTube Automation
 
- Search videos using keywords
- Detect videos and YouTube courses
- Find videos from the configured target channel
- Watch videos for random durations
- Automatically return to YouTube home
- Close mini player automatically
- Retry failed operations
- Continuous execution (24×7)
- Parallel browser sessions
- Human-like scrolling and interaction
 
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
├── config.json
├── main.py
├── youtube_main.py
├── requirements.txt
└── README.md
```
 
---
 
# Requirements
 
- Python 3.10+
- Google Chrome
- Internet Connection
 
Python packages:
 
```bash
pip install -r requirements.txt
```
 
Install ChromeDriver once if required:
 
```bash
seleniumbase install chromedriver
```
 
---
 
# Setup
 
Clone the repository
 
```bash
git clone <repository-url>
cd bot_project
```
 
Create virtual environment
 
### Windows
 
```powershell
python -m venv .venv
.\.venv\Scripts\activate
```
 
### Linux/macOS
 
```bash
python3 -m venv .venv
source .venv/bin/activate
```
 
Install dependencies
 
```bash
pip install -r requirements.txt
```
 
---
 
# Configuration
 
The project uses configuration files instead of hardcoded values.
 
## config.json
 
Contains
 
- Browser configuration
- Parallel sessions
- Search engine settings
- Website settings
- YouTube settings
- Timing values
 
## search_engines.json
 
Contains
 
- Search engine URLs
- Search box locators
- Result locators
- Next page locators
 
## youtube.json
 
Contains
 
- YouTube URL
- Target channel
- Search box locator
- Video locators
- Channel locators
- Logo locator
 
## keywords.json
 
Contains the list of keywords used for automation.
 
---
 
# Entry Points
 
This project contains **two independent automation modules**.
 
---
 
## 1. Search Engine Automation
 
Entry Point
 
```bash
python main.py
```
 
Workflow
 
```
Load Config
      ↓
Load Keywords
      ↓
Open Search Engine
      ↓
Search Keyword
      ↓
Find Target Website
      ↓
Visit Website
      ↓
Visit Internal Links
      ↓
Close Browser
```
 
Supported search engines
 
- Google
- Bing
- Yahoo
- DuckDuckGo
 
---
 
## 2. YouTube Automation
 
Entry Point
 
```bash
python youtube_main.py
```
 
Workflow
 
```
Load Config
      ↓
Load Keywords
      ↓
Open YouTube
      ↓
Search Keyword
      ↓
Find Target Channel Video
      ↓
Watch Video
      ↓
Return to Home
      ↓
Repeat for Next Keyword
```
 
The YouTube module automatically restarts after each cycle, making it suitable for long-running deployments.
 
---
 
# Parallel Sessions
 
Number of browser sessions is controlled from:
 
```json
"sessions": {
    "parallel": 4
}
```
 
Each browser runs independently in its own thread.
 
---
 
# Running the Project
 
## Search Engine Automation
 
```bash
python main.py
```
 
---
 
## YouTube Automation
 
```bash
python youtube_main.py
```
 
---
 
# Continuous Execution
 
The YouTube automation supports continuous execution.
 
Features include:
 
- Automatic restart after every cycle
- Configurable cycle delay
- Retry mechanism for failed operations
- Parallel browser sessions
- Suitable for Windows Task Scheduler deployment
- Graceful shutdown on interruption
 
---
 
# Configuration Files
 
| File | Purpose |
|------|----------|
| config.json | Global project configuration |
| keywords.json | Search keywords |
| search_engines.json | Search engine configuration |
| youtube.json | YouTube configuration |
 
---
 
# Technologies Used
 
- Python
- SeleniumBase
- Selenium WebDriver
- Google Chrome
- Threading
- JSON Configuration
 
---
 
# Future Enhancements
 
- Human-like mouse movement
- Random video interactions
- Recommended video navigation
- Support for additional browsers
- Advanced activity logging
- Improved anti-detection behavior
 
---
 
# Notes
 
- Do not commit `.venv/`
- Do not commit browser cache or temporary files.
- Search engine and YouTube page structures may change over time.
- Locator updates may occasionally be required.
- SeleniumBase automatically manages compatible ChromeDriver versions.
