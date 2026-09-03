SEO Automation Dashboard

Web-based dashboard for monitoring the SEO Automation project. It provides an interface for viewing automation runs, execution status, statistics, and detailed logs for Website/Search and YouTube automation.

Features

Switch between SEARCH (Website Automation) and YOUTUBE.

View recent automation runs and their status.

Open Live Logs for a selected run.

View timestamp, level, action, event status, keyword, search engine, URL, error message, and metadata for log events.

Automatically refresh dashboard data.

Refresh the selected run's logs while Live Logs is open.

Check backend health.

Folder Structure

dashboard/
├── index.html
├── dashboard.js
├── dashboard.css
└── README.md

The exact filenames may vary depending on the project structure.

Backend APIs

The dashboard communicates with the Flask backend.

Dashboard Data

GET /api/dashboard

Used to load dashboard data for the selected automation type and date range.

Supported automation types:

SEARCH
YOUTUBE

Run Logs

GET /api/logs/<run_id>

Returns the chronological log events for a specific automation run.

Log records contain fields such as:

log_id
timestamp
level
keyword
search_engine
action
event_status
url
error_message
metadata
message

Health Check

GET /api/health

Used to check application/backend health.

How Live Logs Work

Select automation
       │
       ▼
Load dashboard data
       │
       ▼
Get recent runs
       │
       ▼
Select active/latest run
       │
       ▼
GET /api/logs/<run_id>
       │
       ▼
Render log timeline
       │
       ▼
Periodic refresh

When switching between Website/Search and YouTube while already on Live Logs, the dashboard should remain on the Live Logs view, select the latest/active run for the newly selected automation, load its logs, and continue refreshing them.

Running the Dashboard

Start the Flask backend from the project root:

python app.py

Then open the dashboard in your browser. For a local setup, this is commonly:

http://127.0.0.1:5000

Use the host and port configured by app.py.

Database

The dashboard depends on PostgreSQL through the Flask backend.

The main tables used for automation monitoring are:

automation_runs
automation_logs

automation_runs stores execution information such as:

run_id

automation_type

original_keyword

search_keyword

browser_mode

started_at

finished_at

status

success_count

failure_count

retry_count

automation_logs stores individual events linked to an automation run_id.

Make sure PostgreSQL is running and the application's database configuration is correct before starting the dashboard.

Local Office Deployment

The dashboard can run independently on each office laptop.

Office Laptop
├── SEO Automation Project
├── Local PostgreSQL
├── Flask Dashboard
└── Browser
    └── http://127.0.0.1:5000

Each laptop can therefore have its own automation data, runs, and logs.

For a new laptop:

Install Python.

Install PostgreSQL.

Clone/copy the SEO Automation project.

Create and activate the Python virtual environment.

Install project dependencies.

Configure the local PostgreSQL connection.

Start PostgreSQL.

Start the Flask application.

Open the dashboard in the browser.

Troubleshooting

Dashboard is empty

Check:

Flask is running.

PostgreSQL is running.

Database credentials/configuration are correct.

The selected automation has runs in the selected date range.

Browser developer tools do not show API errors.

Live Logs show no entries

Check:

A valid run is selected.

The run_id exists in automation_runs.

Logs exist in automation_logs for that run.

/api/logs/<run_id> returns data.

New logs are not appearing

Check:

Auto refresh is running.

The selected run ID is valid.

The automation is writing events to automation_logs.

The browser is successfully calling the logs API.

YouTube logs are missing

Verify that the YouTube automation uses the same run_id when creating the automation run and writing its log events.

Development Notes

Keep automation type values consistent:

SEARCH
YOUTUBE

Live Logs are always associated with a run_id. Do not hard-code run IDs in the frontend.

When changing dashboard code, test both automation modes and verify:

Overview

Recent runs

Live Logs

Automation switching

Live log refresh

YouTube logs

Error handling

Security

Keep database credentials and secrets outside frontend JavaScript.

Do not commit passwords, API keys, or .env files to source control.

Do not expose the local Flask server publicly without appropriate authentication and network security.

Quick Checklist

Flask backend starts successfully.

PostgreSQL connection works.

Overview loads.

SEARCH mode works.

YOUTUBE mode works.

Recent runs appear.

Live Logs run selector works.

Selected run logs load.

Log timeline displays correctly.

Auto refresh works.

Switching automation while on Live Logs keeps the Live Logs view.

YouTube logs are visible.

Errors are displayed clearly.