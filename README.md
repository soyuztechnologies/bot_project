# SEO Automation Bot

Python browser automation (SeleniumBase + Chrome) for three jobs:

1. **Website automation** — searches keywords on Google/Bing/Yahoo/DuckDuckGo, finds your site, visits it like a human.
2. **YouTube automation** — finds your channel's videos, watches them, scrolls like a human.
3. **Generate Backlinks** — submits your URLs to ping / backlink-generator tools (50 sites configured, 49 enabled).

Everything is config-driven (`config.json` + `data/*.json`), runs headless Chrome, supports parallel sessions, and logs every run to MongoDB. A Flask **dashboard** shows runs, live logs and backlink results.

---

## 1. Super-fast setup (new laptop, one command)

On a fresh Windows laptop, paste this single line in PowerShell:

```powershell
powershell -c "irm https://raw.githubusercontent.com/soyuztechnologies/bot_project/master/setup.bat -OutFile setup.bat; .\setup.bat"
```

Or, if you already cloned the repo, just run `setup.bat`.

`setup.bat` does everything by itself (safe to re-run — finished steps are skipped):

1. Installs **Git** (via winget) if missing
2. Installs **Docker Desktop** (via winget) if missing — then it asks you to restart, start Docker Desktop, and re-run it
3. **Clones** the repo if the folder is missing
4. Creates **`.env`** — asks once for your `MONGO_URI_ATLAS` (same value as the working laptop, so the new laptop sees the same data)
5. **Builds** the docker image (downloads Python packages, Chrome, chromedriver automatically)
6. **Runs the bot** — interactive menu: `1` website, `2` youtube, `3` backlinks

Dashboard separately:

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
# source .venv/bin/activate     # Linux / Mac

pip install -r requirements.txt
copy .env.example .env          # then put your MONGO_URI_ATLAS inside
```

Chromedriver is installed automatically at runtime — no manual step needed.

---

## 3. Running

### Interactive launcher (easiest)

```bash
python launcher.py
```

```
==================================================
            SEO AUTOMATION BOT
==================================================
1. Website Automation
2. YouTube Automation
3. Generate Backlinks
==================================================
```

### Direct scripts

```bash
python main.py            # website automation
python youtube_main.py    # youtube automation
python backlink_main.py   # backlinks (all enabled sites x all targets)
```

### Backlinks — useful flags

```bash
python backlink_main.py --dry-run --list
# config + DB check only, no browser. Shows all sites/targets and planned job count.

python backlink_main.py --sites naklov_backlink_maker --max-targets 1
# smoke test: ONE site, ONE target, one browser. Always test new sites like this first.

python backlink_main.py --sites keycdn_ping,keycdn_speed --max-targets 2
# a few sites, first 2 targets.
```

---

## 4. Backlinks — how the 50 sites work

`data/backlink_sites.json` holds 50 site entries, **49 enabled**. Each enabled site has XPath selectors (`fields` → `submit` → `result`) that the generic engine (`automation/backlink/engine.py`) drives — no per-site code needed.

Current totals (verify anytime with `--dry-run --list`):

| Group | Count |
|---|---|
| Enabled sites | 49 |
| Targets (`data/backlink_targets.json`) | 10 (5 website + 5 YouTube) |
| YouTube-only sites (get only the 5 YouTube targets) | 3 |
| **Planned jobs** | **475** (46×10 + 3×5) |

Two special behaviours to know:

- **Target filtering** — the 3 YouTube generators (`kwebby` / `nimtools` / `a2z` youtube tools) carry `target_url_contains: ["youtube.com", "youtu.be"]`, so website URLs are never sent to them. Sites without filter keys accept every target (old behaviour, unchanged).
- **`unmiss_backlink_maker` is intentionally disabled** — it needs a live Cloudflare Turnstile token, so it cannot be automated. Everything else runs.

Result checks are written to avoid false positives (e.g. hidden-until-done panels, injected result tables — never static page text). A few SPA tools use `success_without_result`, which logs an explicit *"submitted but no confirmation element"* caveat instead of pretending.

---

## 5. Dashboard

```bash
python dashboard/app.py
# open http://127.0.0.1:5050
```

Three modes: **SEARCH**, **YOUTUBE**, **BACKLINK**. See recent runs, live logs per `run_id`, per-site backlink results, and start/stop website / YouTube / backlink jobs from the UI. Full details in [`dashboard/README.md`](dashboard/README.md).

---

## 6. Configuration files

| File | Purpose |
|---|---|
| `config.json` | Browser (chrome/headless), parallel sessions, search engines, website + youtube settings, DB selector (`database.current_db`: `atlas` or `local`) |
| `.env` | Secrets — `MONGO_URI_ATLAS`, `MONGO_URI_LOCAL`, `MONGO_DB_NAME`, `GMAIL_APP_PASSWORD`. Never committed (gitignored). |
| `data/keywords.json` | Keywords for website/YouTube runs |
| `data/search_engines.json` | Search-engine URL + locators |
| `data/youtube.json` | YouTube locators |
| `data/backlink_sites.json` | All ping/backlink sites + their XPath configs |
| `data/backlink_targets.json` | URLs to submit (each has `url`, `title`, `keyword`, `category`) |

Database: MongoDB. `config.json → database.current_db` picks `local` or `atlas`; the URI comes from the matching `.env` variable. Collections used: `automation_runs`, `automation_logs`, `backlinks`.

---

## 7. Project structure

```text
bot_project/
├── launcher.py                 # interactive menu (1/2/3)
├── main.py                     # website automation entry
├── youtube_main.py             # youtube automation entry
├── backlink_main.py            # backlinks entry (+ --sites/--max-targets/--dry-run/--list)
├── automation/
│   ├── backlink/               # generic config-driven ping/backlink engine
│   │   ├── engine.py           # generic_submit + site_accepts_target
│   │   ├── backlink_session.py # parallel sessions, job building
│   │   ├── selenium_utils.py   # finds, typing, result waiting
│   │   └── handlers.py
│   ├── search_engine.py website.py youtube.py ...
├── browser/browser.py          # seleniumbase Driver (UC chrome, auto chromedriver)
├── dashboard/app.py            # Flask dashboard (port 5050)
├── data/*.json                 # keywords, engines, sites, targets
├── utils/                      # database, logger, mailer, helpers
├── config.json requirements.txt Dockerfile docker-compose.yml
├── setup.bat                   # one-command fresh-laptop setup
└── .env.example
```

---

## 8. Testing a change (follow this order)

1. `python backlink_main.py --dry-run --list` — config + DB OK, no browser.
2. One site, one target: `python backlink_main.py --sites <site_id> --max-targets 1`.
3. Check the `backlinks` collection: `status` should be `SUCCESS` with `result_xpath` pointing at a real selector (not `success_without_result`).
4. Then scale up: more sites → `--max-targets 3` → full run.

---

## 9. Troubleshooting

| Problem | Fix |
|---|---|
| `No enabled backlink sites` / config error | Check `data/backlink_sites.json` is valid JSON and entries have `enabled: true` |
| MongoDB connection fails | `.env` must contain the URI named in `config.json` (`MONGO_URI_ATLAS` when `current_db` is `atlas`) |
| Chrome/driver errors | Delete the cached driver and re-run — `browser.py` re-downloads it automatically |
| A site logs `CaptchaSkipped` | That site showed a bot-check; the job is marked failed (with `captcha_encountered`) and the run continues with the next site |
| Docker: `docker info` fails | Start Docker Desktop and wait for green "running" |
| Dashboard empty | Flask must run (`python dashboard/app.py`), MongoDB reachable, and runs must exist in the selected date range/mode |

Notes: VPN code is commented out everywhere (nothing to configure). E-mail reports need `GMAIL_APP_PASSWORD` in `.env`, otherwise they are skipped. Site page structures change over time — if a site starts failing, re-check its form selectors live and update its entry.
