# 🚀 SEO Automation Bot

Welcome to the **SEO Automation Bot**! This project uses browser automation (SeleniumBase + Chrome) to simulate human-like interactions across different search engines and websites. It helps you boost your SEO through three main workflows:

1. 🌐 **Website Automation:** Searches your keywords on Google/Bing/Yahoo/DuckDuckGo, finds your target website, clicks it, and browses it like a real human.
2. 📺 **YouTube Automation:** Searches for your videos, watches them, and scrolls naturally to increase engagement.
3. 🔗 **Generate Backlinks:** Automatically submits your URLs to 49 different ping and backlink-generator websites.

All runs are recorded in a MongoDB database, and you can monitor everything live using the built-in Flask **Dashboard**!

---

## 🛠️ 1. Prerequisites

Before you start, you will need:
1. **A MongoDB Atlas Account:** You need a free cloud database to store your logs. Get your connection string (e.g., `mongodb+srv://user:pass@cluster...`).
2. **Windows OS:** The automated setup script is designed for Windows.

---

## 🚀 2. Easy Setup (Recommended for New Users)

If you are on a fresh Windows machine, you can install everything automatically with a single command!

Open **Command Prompt (`cmd`)** as Administrator and run:
```cmd
curl.exe -L -o setup.bat https://raw.githubusercontent.com/soyuztechnologies/bot_project/master/setup.bat && setup.bat
```

*(Alternatively, if you already cloned the project, just double-click or run `setup.bat` from the project folder).*

**What does this script do?**
- Installs **Git** and **Docker Desktop** (if you don't have them).
- Creates your **`.env`** file and asks you for your MongoDB Atlas connection string.
- Downloads Chrome, Python packages, and Chromedriver automatically.
- Launches the interactive bot menu!

---

## ⚙️ 3. Configuration (How to customize for YOUR site)

Before running the bot, you need to tell it what to search for and where to go. All configuration is done in the `data/` folder and `config.json` file.

1. **`config.json`**: Open this file to set your target website domain and how many browser windows should open in parallel.
2. **`.env`**: This holds your secret `MONGO_URI_ATLAS` connection string. Never share this file!
3. **`data/keywords.json`**: List the search terms you want the bot to look for.
4. **`data/search_engines.json`**: Controls which search engines (Google, Bing, etc.) the bot uses.
5. **`data/backlink_targets.json`**: List the URLs you want to generate backlinks for.

---

## 🏃 4. Running the Bot

The easiest way to use the bot is via the **Interactive Launcher**.

Open your terminal in the project folder and run:
```bash
python launcher.py
```
You will see a menu where you can simply type `1`, `2`, or `3` to start Website Automation, YouTube Automation, or Backlink Generation!

### 🧹 Database Maintenance
To keep your database fast and clean, you can delete logs older than 30 days. Run:
```bash
python cleanup_atlas_logs.py
```
*Note: This will securely prompt you for your MongoDB Atlas password before safely removing old records.*

---

## 📊 5. Viewing the Dashboard

You can monitor your bot's progress in real-time with the built-in dashboard!

To start the dashboard locally, run:
```bash
python dashboard/app.py
```
Then, open your web browser and go to: **[http://localhost:5050](http://localhost:5050)**

From here you can view live logs, backlink results, and start/stop the automations.

*(If you are using Docker, you can start it with `docker compose up -d dashboard`)*

---

## 🤓 6. Advanced Usage & Manual Setup

### Manual Setup (Without `setup.bat`)
If you prefer setting things up yourself without Docker:
```bash
git clone https://github.com/soyuztechnologies/bot_project.git
cd bot_project

python -m venv .venv
.\.venv\Scripts\activate        # Windows (use source .venv/bin/activate for Mac/Linux)

pip install -r requirements.txt
copy .env.example .env          # Open .env and add your MONGO_URI_ATLAS
```

### Direct Entry Points (Command Line)
You can bypass the interactive menu by running these scripts directly:
```bash
python main.py            # Website automation
python youtube_main.py    # YouTube automation
python backlink_main.py   # Backlinks automation
```

### Advanced Backlink Testing
When adding new backlink sites or debugging, use these flags:
```bash
# Validates your config without opening a browser
python backlink_main.py --dry-run --list

# Smoke test: Tests just ONE specific site with ONE target
python backlink_main.py --sites naklov_backlink_maker --max-targets 1
```

### Important Backlink Notes
- **50 configured sites:** 49 are enabled. `unmiss_backlink_maker` is disabled due to strict Cloudflare Turnstile blocks.
- **YouTube filtering:** Sites like `kwebby` or `nimtools` will automatically *only* process YouTube URLs.
- **Verification:** Always run `python backlink_main.py --dry-run --list` after editing `data/backlink_sites.json` to verify everything is correct.

---

## 📂 7. Project Structure

```text
bot_project/
├── launcher.py                 # Interactive menu (1/2/3)
├── main.py                     # Website automation entry point
├── youtube_main.py             # YouTube automation entry point
├── backlink_main.py            # Backlinks entry point
├── cleanup_atlas_logs.py       # Utility to delete Atlas logs older than 30 days
├── automation/                 # Core logic for clicking, typing, and searching
├── browser/                    # Browser startup and profile management
├── dashboard/                  # Flask web dashboard (port 5050)
├── data/                       # Your JSON configuration (keywords, targets)
├── utils/                      # Database connection, logging, exceptions
├── config.json                 # Main bot settings
└── setup.bat                   # 1-click installer
```

---

## 🚑 8. Troubleshooting

| Problem | Solution |
|---|---|
| **MongoDB connection failure** | Ensure your `.env` file has the correct `MONGO_URI_ATLAS` string and your IP is whitelisted in MongoDB Atlas. |
| **Chrome/Driver crashes** | Delete your `.venv` folder and run manual setup again. `browser.py` will re-download a fresh chromedriver. |
| **Empty Dashboard** | Ensure `python dashboard/app.py` is running, your database is connected, and the bot has actually finished some runs. |
| **CaptchaSkipped in logs** | The bot hit a captcha. This is normal; it will safely skip and try the next search engine. |
