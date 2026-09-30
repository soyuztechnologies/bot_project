# SEO Automation Dashboard

Web dashboard (Flask) for watching the SEO Automation Bot: recent runs, live logs per run, per-site backlink results, and start/stop buttons for all three automations.

Three modes: **SEARCH** (website automation), **YOUTUBE**, **BACKLINK**.

---

## 1. Run it

From the **project root** (`bot_project/`):

```bash
python dashboard/app.py
```

Then open in your browser:

```text
http://127.0.0.1:5050
```

With Docker instead:

```bash
docker compose up -d dashboard
# open http://localhost:5050
```

Host/port can be overridden without code changes via environment variables
(defaults keep laptop behaviour):

```bash
DASHBOARD_HOST=0.0.0.0 DASHBOARD_PORT=5050 python dashboard/app.py
```

---

## 2. What you can do in the UI

- **Overview** — recent automation runs with status, counts and durations.
- **Mode switch** — flip between SEARCH / YOUTUBE / BACKLINK. If you switch while on Live Logs, the view stays on Live Logs and loads the latest run of the newly selected mode.
- **Live Logs** — pick a run, see its events as a timeline (`timestamp, level, action, status, keyword, engine, url, error`). Auto-refreshes while open.
- **Backlinks view** — per-site submission table from the `backlinks` collection: `site_id, target_url, status, result_text`. Summary + per-site breakdown included.
- **Run jobs from the UI** — start/stop Website, YouTube and Backlink jobs (they run `main.py` / `youtube_main.py` / `backlink_main.py` in the background). Only one backlink job at a time; stopping kills its process tree.

---

## 3. Backend API

| Method + path | Purpose |
|---|---|
| `GET /` | Dashboard page |
| `GET /api/dashboard?mode=SEARCH\|YOUTUBE\|BACKLINK` | Overview data (runs, stats) for a mode + date range |
| `GET /api/logs/<run_id>` | Chronological log events for one run |
| `GET /api/backlinks` | Backlink summary, per-site table, recent submissions |
| `POST /api/backlinks/generate` | Start a backlink job in the background (optional `sites` filter, same as CLI `--sites`) |
| `POST /api/backlinks/stop` | Stop the running backlink job |
| `GET /api/backlinks/status` | Current backlink job state |
| `POST /api/automation/start` | Start a website/YouTube job |
| `POST /api/automation/stop` | Stop a website/YouTube job |
| `GET /api/automation/status` | Current website/YouTube job state |
| `GET /api/health` | Backend + database health |

Log records contain: `timestamp, level, keyword, search_engine/engine, action, event_status, url, error_message, message, metadata`.

---

## 4. Database (MongoDB)

Same database as the bot — configured via project-root `config.json` (`database.current_db`: `atlas` or `local`) + `.env` (`MONGO_URI_ATLAS` / `MONGO_URI_LOCAL`).

Collections used:

- **`automation_runs`** — one doc per run: `run_id, automation_type, keyword, browser_mode, started_at, finished_at, status, success/failure counts`.
- **`automation_logs`** — individual events, linked by `run_id`.
- **`backlinks`** — one doc per site × URL submission: `site_id, target_url, status, result_text, result_xpath`.

---

## 5. Folder structure

```text
dashboard/
├── app.py                  # Flask backend + all /api routes (port 5050)
├── templates/
│   └── index.html          # dashboard page
├── static/
│   ├── dashboard.js        # frontend logic
│   └── dashboard.css
├── dashboard_requirements.txt
└── README.md
```

---

## 6. Troubleshooting

| Problem | Check |
|---|---|
| Dashboard empty | Flask running? MongoDB reachable (see `/api/health`)? Runs exist in the selected mode + date range? |
| Live Logs show nothing | A valid run is selected; its `run_id` exists in `automation_runs`; `GET /api/logs/<run_id>` returns data |
| New logs not appearing | Auto-refresh on? The automation is still writing to `automation_logs`? |
| Backlinks view empty | No `backlink_main.py` run yet — start one from the UI or CLI |
| Start-job fails | Another job of the same kind already running? Check `.../status` endpoints |
| Port already in use | Change port: `DASHBOARD_PORT=5051 python dashboard/app.py` |

---

## 7. Notes for developers

- Keep automation-type values exactly `SEARCH`, `YOUTUBE`, `BACKLINK` everywhere.
- Live Logs are always keyed by `run_id` — never hard-code run IDs in the frontend.
- After changing dashboard code, test all three modes: overview, recent runs, live logs, mode switching, job start/stop, error display.
- Secrets stay out of frontend JS: no passwords, API keys or `.env` content in `static/` or `templates/`. Never commit `.env`.
- The job **stop** buttons use Windows `taskkill`; on Linux/Docker the backend falls back to process-tree termination — stopping still works, but verify it on your platform once.
- Do not expose the Flask server publicly without authentication and proper network security.
