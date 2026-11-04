# 🚀 SEO Automation Bot

Welcome to the **SEO Automation Bot**! This project uses browser automation (SeleniumBase + Chrome) to simulate human-like interactions across different search engines and websites. It helps you boost your SEO through three main workflows:

1. 🌐 **Website Automation:** Searches your keywords on Google/Bing/Yahoo/DuckDuckGo, finds your target website, clicks it, and browses it like a real human.
2. 📺 **YouTube Automation:** Searches for your videos, watches them, and scrolls naturally to increase engagement.
3. 🔗 **Generate Backlinks:** Automatically submits your URLs to 49 different ping and backlink-generator websites.

All runs are recorded in a MongoDB database, and you can monitor everything live and control automations using the built-in Flask **Web Dashboard**!

---

## 🛠️ 1. Prerequisites

Before you start, you will need:
1. **A MongoDB Atlas Account:** A cloud database to store your runs and logs (free tier works great). Get your connection string (e.g., `mongodb+srv://user:pass@cluster...`). Alternatively, a local MongoDB instance can be used.
2. **Chrome Browser:** Google Chrome installed on your machine.
3. **Windows OS:** The automated 1-click installer is designed for Windows (macOS and Linux users can follow the [Manual Setup](#-7-manual-setup-without-setupbat)).

---

## 🚀 2. Easy Setup (Recommended for Windows)

If you are on a fresh Windows machine, you can install everything automatically with a single command!

Open **Command Prompt (`cmd`)** as Administrator and run:
```cmd
curl.exe -L -o setup.bat https://raw.githubusercontent.com/soyuztechnologies/bot_project/master/setup.bat && setup.bat
```

*(Alternatively, if you already cloned the project, just double-click or run `setup.bat` from the project folder).*

**What does this script do?**
- Installs **Git** and **Docker Desktop** (if you don't already have them).
- Creates your **`.env`** file and prompts you for your MongoDB Atlas connection string.
- Downloads Chrome, Python packages, and Chromedriver automatically.
- Launches the interactive bot launcher menu!

---

## ⚙️ 3. Configuration

Before running the bot, configure your target website, keywords, and credentials. All configuration is done in `config.json`, `.env`, and the `data/` directory:

1. **`config.json`**: Set your target website domain, database mode (`atlas` or `local`), and how many browser windows should open in parallel.
2. **`.env`**: Holds your secret connection strings (`MONGO_URI_ATLAS`, `MONGO_URI_LOCAL`). Never share or commit this file!
3. **`data/keywords.json`**: List the search terms you want the bot to look for.
4. **`data/search_engines.json`**: Controls search engines (Google, Bing, Yahoo, DuckDuckGo) used by the bot.
5. **`data/backlink_targets.json`**: List the URLs you want to generate backlinks for.
6. **`data/backlink_sites.json`**: List and configuration of ping and backlink submission sites.

---

## 🏃 4. Running the Automations

### Interactive Launcher (Easiest)
Open your terminal in the project folder and run:
```bash
python launcher.py
```
You will see a menu where you can simply type `1`, `2`, or `3` to start:
- `1` — Website Automation (Google, Bing, Yahoo, DuckDuckGo)
- `2` — YouTube Automation
- `3` — Backlink Automation

### Direct Command-Line Entry Points
You can bypass the interactive menu by running the automation scripts directly:
```bash
python main.py            # Website automation
python youtube_main.py    # YouTube automation
python backlink_main.py   # Backlinks automation
```

### Advanced Backlink Testing & Flags
When adding new backlink sites or debugging, use these CLI flags:
```bash
# Validates your config without opening a browser
python backlink_main.py --dry-run --list

# Smoke test: Tests just ONE specific site with ONE target
python backlink_main.py --sites naklov_backlink_maker --max-targets 1
```

> **Important Backlink Notes:**
> - **50 Configured Sites:** 49 are enabled. `unmiss_backlink_maker` is disabled due to strict Cloudflare Turnstile blocks.
> - **YouTube Filtering:** Sites like `kwebby` or `nimtools` will automatically *only* process YouTube URLs.
> - **Verification:** Always run `python backlink_main.py --dry-run --list` after editing `data/backlink_sites.json` to verify everything is correct.

### 🧹 Database Maintenance
To keep your database fast and clean, delete logs older than 30 days:
```bash
python cleanup_atlas_logs.py
```
*(This will securely prompt you for your MongoDB password before safely removing old records).*

---

## 📊 5. Web Dashboard

The bot includes a built-in Flask web dashboard for real-time monitoring, live logs, backlink statistics, and job controls across all three modes: **SEARCH** (website automation), **YOUTUBE**, and **BACKLINK**.

### Running the Dashboard

**Local Python:**
From the project root (`bot_project/`):
```bash
python dashboard/app.py
```
Then open in your browser: **[http://localhost:5050](http://localhost:5050)** (or `http://127.0.0.1:5050`)

**Via Docker:**
```bash
docker compose up -d dashboard
# Open http://localhost:5050
```

**Custom Host/Port:**
Override without code changes using environment variables:
```bash
DASHBOARD_HOST=0.0.0.0 DASHBOARD_PORT=5050 python dashboard/app.py
```

### Dashboard Features
- **Overview:** Displays recent automation runs with status, success/failure counts, and execution durations.
- **Mode Switch:** Switch between **SEARCH**, **YOUTUBE**, and **BACKLINK**. Switching modes while on Live Logs retains the Live Logs view and loads the latest run of the newly selected mode.
- **Live Logs:** Select a run to inspect its events as a real-time timeline (`timestamp, level, action, status, keyword, engine, url, error`). Refreshes automatically while open.
- **Backlinks View:** Per-site submission table sourced from the `backlinks` collection (`site_id, target_url, status, result_text`), with aggregate summary and per-site breakdowns.
- **Job Controls:** Start and stop Website, YouTube, and Backlink jobs directly from the UI (executed as `main.py` / `youtube_main.py` / `backlink_main.py` background processes). Backlink jobs enforce a limit of one concurrent run; stopping terminates the process tree.

### Backend REST API

| Method & Path | Purpose |
|---|---|
| `GET /` | Dashboard web page |
| `GET /api/dashboard?mode=SEARCH\|YOUTUBE\|BACKLINK` | Overview data (runs, stats) for a mode + date range |
| `GET /api/logs/<run_id>` | Chronological log events for one run |
| `GET /api/backlinks` | Backlink summary, per-site table, recent submissions |
| `POST /api/backlinks/generate` | Start a backlink job in the background (supports optional `sites` filter) |
| `POST /api/backlinks/stop` | Stop the running backlink job |
| `GET /api/backlinks/status` | Current backlink job state |
| `POST /api/automation/start` | Start a website or YouTube automation job |
| `POST /api/automation/stop` | Stop a website or YouTube automation job |
| `GET /api/automation/status` | Current website or YouTube job state |
| `GET /api/health` | Backend and database connectivity health check |

---

## 🗄️ 6. Database Schema (MongoDB)

Both the bot and the dashboard share the same MongoDB database, configured via project-root `config.json` (`database.current_db`: `atlas` or `local`) and `.env` (`MONGO_URI_ATLAS` / `MONGO_URI_LOCAL`).

### Collections Used:
- **`automation_runs`**: One document per run (`run_id`, `automation_type`, `keyword`, `browser_mode`, `user_name`, `user_email`, `started_at`, `finished_at`, `status`, `success/failure counts`).
- **`automation_logs`**: Individual event logs linked by `run_id` (`timestamp`, `level`, `keyword`, `search_engine`, `action`, `event_status`, `url`, `error_message`, `message`, `metadata`).
- **`backlinks`**: One document per site × URL submission (`site_id`, `target_url`, `status`, `result_text`, `result_xpath`, `created_at`).
- **`user_settings`**: Stores user profile and notification configuration set from the Bot UI (`email`, `email_to`, `user_name`, `browser_name`, `parallel_sessions`, `updated_at`).

---

## 🤓 7. Manual Setup (Without `setup.bat`)

If you prefer setting things up manually on Windows, macOS, or Linux without `setup.bat`:

```bash
# 1. Clone repository
git clone https://github.com/soyuztechnologies/bot_project.git
cd bot_project

# 2. Create and activate virtual environment
python -m venv .venv

# On Windows:
.\.venv\Scripts\activate
# On macOS / Linux:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
pip install -r dashboard/dashboard_requirements.txt

# 4. Configure environment
copy .env.example .env     # On Linux/macOS: cp .env.example .env
# Open .env and add your MONGO_URI_ATLAS or MONGO_URI_LOCAL
```

---

## 📂 8. Project Structure

```text
bot_project/
├── launcher.py                 # Interactive terminal menu (Website / YouTube / Backlinks)
├── main.py                     # Website automation entry point
├── youtube_main.py             # YouTube automation entry point
├── backlink_main.py            # Backlinks automation entry point
├── cleanup_atlas_logs.py       # Utility to delete Atlas logs older than 30 days
├── config.json                 # Global bot settings
├── requirements.txt            # Python dependencies
├── setup.bat                   # 1-click Windows installer
├── automation/                 # Core automation logic (actions, flows, drivers)
├── browser/                    # Browser startup, stealth options, and profiles
├── dashboard/                  # Flask web dashboard (port 5050)
│   ├── app.py                  # Flask backend server & REST API
│   ├── templates/              # HTML frontend templates
│   │   └── index.html          # Single-page dashboard UI
│   ├── static/                 # Frontend assets
│   │   ├── dashboard.js        # UI logic and API polling
│   │   └── dashboard.css       # Dashboard styles
│   └── dashboard_requirements.txt
├── data/                       # JSON configurations
│   ├── keywords.json           # Search keywords
│   ├── search_engines.json     # Search engine definitions
│   ├── backlink_targets.json   # URLs to ping / generate backlinks for
│   └── backlink_sites.json     # 50 backlink site configurations
└── utils/                      # Database connection, logging, exceptions
```

---

## 👨‍💻 9. Developer Guidelines & Notes

- **Consistent Mode Keys**: Keep automation-type values strictly `SEARCH`, `YOUTUBE`, and `BACKLINK` across the database, backend, and frontend.
- **Run ID Correlation**: Live Logs are always keyed by `run_id` — never hard-code run IDs in the frontend.
- **Testing Changes**: After changing dashboard code, test all three modes: overview, recent runs, live logs, mode switching, and job start/stop controls.
- **Process Management**: The job **stop** controls use Windows `taskkill /T /F`; on Linux/Docker, the backend falls back to process-tree termination.
- **Security**:
  - Keep secrets out of frontend JS: no passwords, API keys, or `.env` contents in `static/` or `templates/`. Never commit `.env`.
  - Do not expose the Flask server publicly without authentication and proper network security.

---

## 🚑 10. Troubleshooting

| Problem | Cause & Solution |
|---|---|
| **MongoDB connection failure** | Ensure your `.env` file has the correct `MONGO_URI_ATLAS` string and your IP is whitelisted in MongoDB Atlas Network Access. Verify database connectivity via `/api/health`. |
| **Chrome / Driver crashes** | Delete your `.venv` folder and run manual setup again. `browser.py` will automatically re-download a fresh chromedriver. |
| **Empty Dashboard** | Ensure `python dashboard/app.py` is running, your database is connected, and the bot has recorded runs for the selected mode and date range. |
| **Live Logs show nothing** | Verify that a valid run is selected, its `run_id` exists in `automation_runs`, and `GET /api/logs/<run_id>` returns data. |
| **New logs not appearing** | Ensure auto-refresh is enabled in the UI and the automation process is still actively writing to `automation_logs`. |
| **Backlinks view empty** | No `backlink_main.py` run has executed yet — trigger one from the dashboard UI or CLI. |
| **Start-job fails** | Another job of the same kind is already running. Check the `/api/automation/status` or `/api/backlinks/status` endpoints. |
| **Port already in use** | Port 5050 is occupied. Start on another port: `DASHBOARD_PORT=5051 python dashboard/app.py`. |
| **CaptchaSkipped in logs** | The bot hit a CAPTCHA. This is normal behavior; it will safely skip and try the next search engine. |
