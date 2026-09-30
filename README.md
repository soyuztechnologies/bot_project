# SEO Automation Bot

Python browser automation (SeleniumBase + Chrome) for three workflows:

1. **Website automation** — searches keywords on Google/Bing/Yahoo/DuckDuckGo, finds the target site, and visits it with human-like interaction.
2. **YouTube automation** — locates the target channel's videos, watches them, and scrolls with human-like interaction.
3. **Generate Backlinks** — submits target URLs to ping and backlink-generator tools (50 sites configured, 49 enabled).

The project is fully configuration-driven (`config.json` + `data/*.json`), runs headless Chrome with parallel sessions, and logs every run to MongoDB. A Flask **dashboard** displays runs, live logs, and backlink results.

---

## 1. One-command setup (fresh Windows machine)

Requires only `cmd` (uses the built-in `curl.exe`; no PowerShell or manual installs needed):

```cmd
curl.exe -L -o setup.bat https://raw.githubusercontent.com/soyuztechnologies/bot_project/master/setup.bat && setup.bat
```

PowerShell alternative (equivalent):

```powershell
irm https://raw.githubusercontent.com/soyuztechnologies/bot_project/master/setup.bat -OutFile setup.bat; .\setup.bat
```

If the repository is already cloned, run `setup.bat` from the project root.

`setup.bat` is idempotent — every step verifies state first and skips completed work.
It elevates itself to administrator, then proceeds automatically:

1. Installs **Git** if missing (winget fast-path, otherwise a direct download — winget is not required)
2. Installs **Docker Desktop** if missing (winget fast-path, otherwise a direct download, including the WSL2 prerequisite), **starts the engine itself** and waits for it — a restart is requested only if the engine still does not come up, after which the same command resumes where it stopped
3. **Clones** the repository if the project folder is missing
4. Creates **`.env`** — prompts once for `MONGO_URI_ATLAS` (use the same value as the working machine so all machines share one database)
5. **Builds** the Docker image (Python packages, Chrome, and chromedriver are downloaded automatically)
6. **Runs the bot** — interactive menu: `1` website, `2` YouTube, `3` backlinks

Dashboard (separate service):

```bash
docker compose up -d dashboard
# open http://localhost:5050
```

---

## 2. Manual setup (without Docker)

```bash
git clone https://github.com/soyuztechnologies/bot_project.git
cd bot_project

python -m venv .venv
.\.venv\Scripts\activate        # Windows
# source .venv/bin/activate     # Linux / macOS

pip install -r requirements.txt
copy .env.example .env          # then set MONGO_URI_ATLAS inside
```

Chromedriver is installed automatically at runtime — no manual step required.

---

## 3. Running

### Interactive launcher (recommended)

```bash
python launcher.py
```

```text
==================================================
            SEO AUTOMATION BOT
==================================================
1. Website Automation
2. YouTube Automation
3. Generate Backlinks
==================================================
```

### Direct entry points

```bash
python main.py            # website automation
python youtube_main.py    # YouTube automation
python backlink_main.py   # backlinks (all enabled sites x all targets)
```

### Backlink flags

```bash
python backlink_main.py --dry-run --list
# Validates config + database without opening a browser.
# Lists all sites/targets and the planned job count.

python backlink_main.py --sites naklov_backlink_maker --max-targets 1
# Smoke test: ONE site, ONE target, one browser.
# Always verify new sites this way first.

python backlink_main.py --sites keycdn_ping,keycdn_speed --max-targets 2
# Multiple sites, first two targets.
```

---

## 4. Backlinks — site inventory

`data/backlink_sites.json` contains 50 site entries, **49 enabled**. Each enabled site declares XPath selectors (`fields` → `submit` → `result`) consumed by the generic engine (`automation/backlink/engine.py`) — no per-site code is required.

Current totals (confirm at any time with `--dry-run --list`):

| Group | Count |
|---|---|
| Enabled sites | 49 |
| Targets (`data/backlink_targets.json`) | 10 (5 website + 5 YouTube) |
| YouTube-only sites (receive only the 5 YouTube targets) | 3 |
| **Planned jobs** | **475** (46 × 10 + 3 × 5) |

Behaviours to be aware of:

- **Target filtering** — the three YouTube generators (`kwebby`, `nimtools`, `a2z` YouTube tools) declare `target_url_contains: ["youtube.com", "youtu.be"]`, so website URLs are never submitted to them. Sites without filter keys accept every target (previous behaviour, unchanged).
- **`unmiss_backlink_maker` is deliberately disabled** — the tool requires a live Cloudflare Turnstile token and cannot be automated safely.
- **Result checks avoid false positives** — selectors target hidden-until-done panels and injected result tables, never static page text. A small number of SPA tools use `success_without_result`, which records an explicit *"submitted but no confirmation element rendered"* caveat instead of a false success.

---

## 5. Dashboard

```bash
python dashboard/app.py
# open http://127.0.0.1:5050
```

Three modes: **SEARCH**, **YOUTUBE**, **BACKLINK**. Recent runs, per-`run_id` live logs, per-site backlink results, and start/stop controls for all three automations. Full reference: [`dashboard/README.md`](dashboard/README.md).

---

## 6. Configuration reference

| File | Purpose |
|---|---|
| `config.json` | Browser (Chrome/headless), parallel sessions, search engines, website and YouTube settings, database selector (`database.current_db`: `atlas` or `local`) |
| `.env` | Secrets — `MONGO_URI_ATLAS`, `MONGO_URI_LOCAL`, `MONGO_DB_NAME`, `GMAIL_APP_PASSWORD`. Gitignored; never committed. |
| `data/keywords.json` | Keywords for website/YouTube runs |
| `data/search_engines.json` | Search-engine URLs and locators |
| `data/youtube.json` | YouTube locators |
| `data/backlink_sites.json` | Ping/backlink sites and their XPath configurations |
| `data/backlink_targets.json` | Submission targets (`url`, `title`, `keyword`, `category`) |

Database: MongoDB. `config.json → database.current_db` selects `local` or `atlas`; the connection string is read from the matching `.env` variable. Collections: `automation_runs`, `automation_logs`, `backlinks`.

---

## 7. Project structure

```text
bot_project/
├── launcher.py                 # interactive menu (1/2/3)
├── main.py                     # website automation entry point
├── youtube_main.py             # YouTube automation entry point
├── backlink_main.py            # backlinks entry point (--sites/--max-targets/--dry-run/--list)
├── automation/
│   ├── backlink/               # config-driven ping/backlink engine
│   │   ├── engine.py           # generic_submit + site_accepts_target
│   │   ├── backlink_session.py # parallel sessions, job construction
│   │   ├── selenium_utils.py   # element location, typing, result waiting
│   │   └── handlers.py
│   ├── search_engine.py website.py youtube.py ...
├── browser/browser.py          # SeleniumBase driver (UC Chrome, automatic chromedriver)
├── dashboard/app.py            # Flask dashboard (port 5050)
├── data/*.json                 # keywords, engines, sites, targets
├── utils/                      # database, logger, mailer, helpers
├── config.json requirements.txt Dockerfile docker-compose.yml
├── setup.bat setup.ps1         # one-command fresh-machine setup
└── .env.example
```

---

## 8. Verification workflow

Follow this order when changing sites or configuration:

1. `python backlink_main.py --dry-run --list` — validates config and database; no browser launched.
2. Single-site smoke test: `python backlink_main.py --sites <site_id> --max-targets 1`.
3. Inspect the `backlinks` collection: `status` should be `SUCCESS` with `result_xpath` referencing a real selector (not `success_without_result`).
4. Scale up gradually: more sites → `--max-targets 3` → full run.

---

## 9. Troubleshooting

| Problem | Resolution |
|---|---|
| Configuration error / no enabled sites | Validate `data/backlink_sites.json` parses as JSON and entries carry `enabled: true` |
| MongoDB connection failure | `.env` must define the URI named by `config.json` (`MONGO_URI_ATLAS` when `current_db` is `atlas`) |
| Chrome/driver errors | Remove the cached driver and re-run — `browser.py` re-downloads a matching driver automatically |
| `CaptchaSkipped` for a site | The site presented a bot check; the job is recorded as failed (`captcha_encountered`) and the run continues with the next site |
| Docker daemon unreachable | Start Docker Desktop and wait for the green "running" status |
| Empty dashboard | Flask must be running (`python dashboard/app.py`), MongoDB reachable, and runs must exist for the selected mode and date range |

Additional notes: VPN integration is commented out throughout the codebase and requires no configuration. Report e-mails require `GMAIL_APP_PASSWORD` in `.env` and are otherwise skipped. Third-party page structures change over time — when a site begins failing, re-inspect its form selectors against the live page and update its entry.
