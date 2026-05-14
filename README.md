# Report Dashboard v2

Local dashboard for tracking HTML report files, with support for AI triage reports and daily briefings.

## Repository layout

```
server.py                          ← FastAPI server
requirements.txt
static\
  index.html                       ← Single-page dashboard UI
data\
  ai-triage\
    Reports\                       ← Watched folder: YYYYMMDD\*.html
    script\
      md_to_html.py                ← Convert triage .md → .html
  Daily briefing\
    Reports\                       ← Briefings folder: YYYY-MM-DD.html
    script\
      md_to_html.py                ← Convert briefing .md → .html
shell\
  run_server.cmd                   ← Kill any existing :8765 process, then start server
  run_silent.vbs                   ← Launch server.py in a hidden window (no console)
Cowork tasks\
  Cowork-Jira-Triage.md            ← Agent task: poll Jira + Gmail → ai-triage reports
  Cowork-Daily-Briefing.md         ← Agent task: daily briefing → briefing HTML
```

### Expected reports folder structure

```
Reports\
  20260506\
    Discover_LIT-668581_20260506_150233.html
    Triage_LIT-669672_20260506_130425.html
  20260507\
    Reply_LIT-667673_20260507_190644.html
```

### Filename convention parsed automatically

```
action_ticket_YYYYMMDD_HHmmSS.html      →  action="Triage"  ticket="LIT-5678"  date="2026-05-08"  time="14:30:22"
```

- **action** — first `_`-delimited segment (e.g. `Reply`, `Verify`, `Discover`, `Triage`)
- **ticket** — middle segment if present (e.g. `SAGE-1234`, `LIT-5678901`)
- **date** — 8-digit segment before the time (YYYYMMDD → YYYY-MM-DD)
- **time** — trailing 6-digit segment (HHMMSS → HH:MM:SS)

### Daily briefing convention

Files in the briefings folder must be named `YYYY-MM-DD.html` (e.g. `2026-05-14.html`).

## Setup

```bat
pip install -r requirements.txt
```

## Run

```bat
REM Defaults: reports  = %userprofile%\Documents\Claude\ai-triage
REM           briefings = %userprofile%\Documents\Claude\Daily briefing\Reports
REM           port      = 8765
python server.py

REM Custom paths or port
python server.py --reports-dir "D:\Reports"
python server.py --briefings-dir "D:\Briefings"
python server.py --port 9000
```

Or use the (Windows) shell helpers:

```bat
shell\run_server.cmd     ← interactive (stops any existing :8765 process first)
shell\run_silent.vbs     ← background / no console window (to use with Windows Task Scheduler)
```

Then open → **http://localhost:8765**

## Features

| Feature | Detail |
|---------|--------|
| File watcher | New/modified `.html` files detected instantly, no polling |
| SQLite state | `dashboard_state.db` next to `server.py` — persists across restarts |
| Filename parsing | Action, ticket, date, time extracted automatically |
| Manual tasks | Create ad-hoc tasks directly in the dashboard (no file needed) |
| Status workflow | New → In Review → Done / Canceled / Flagged |
| Bulk actions | Select multiple rows, change status in one click |
| Report preview | Sandboxed iframe renders the HTML file with dark-mode injection |
| Daily briefings | Separate tab serves `YYYY-MM-DD.html` briefing files |
| Analytics tab | Status bars, action breakdown, date heatmap, ticket completion |
| Auto-refresh | Every 20 s; manual Rescan button also available |
| Mark seen | First open timestamp recorded; unseen reports highlighted |

## REST API

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/reports` | List with filter/sort/paginate |
| GET | `/api/reports/{id}` | Single report + event log |
| GET | `/api/reports/{id}/preview` | Raw HTML for iframe |
| POST | `/api/reports/{id}/mark-seen` | Record first-open timestamp |
| PATCH | `/api/reports/{id}/status` | `{status, note}` |
| POST | `/api/reports/bulk-status` | `{ids[], status, note}` |
| GET | `/api/stats` | Aggregated stats |
| GET | `/api/meta` | Distinct actions + dates for dropdowns |
| POST | `/api/scan` | Manual rescan |
| POST | `/api/manual` | Create manual task `{title, description?, ticket?}` |
| PATCH | `/api/manual/{id}` | Update manual task title/ticket |
| GET | `/api/briefings` | List available briefing files |
| GET | `/api/briefings/{date}` | Serve briefing HTML (date = `YYYY-MM-DD`) |

## Status values

`new` · `in_review` · `done` · `canceled` · `flagged`

## md_to_html conversion

Both `data/ai-triage/script/md_to_html.py` and `data/Daily briefing/script/md_to_html.py` convert a markdown report to a self-contained, styled HTML file ready to be placed in the watched folder:

```bat
python data\ai-triage\script\md_to_html.py input.md output.html
```

## Cowork tasks

The `Cowork tasks/` folder contains the Claude task definitions that produce the HTML reports consumed by this dashboard.

| File | Task | Output |
|------|------|--------|
| `Cowork-Jira-Triage.md` | Polls Jira for assigned and engagement tickets updated since the last run; assesses each for required action; generates one scoped markdown report per actionable item, then converts it to HTML | `data\ai-triage\Reports\YYYYMMDD\<action>_<TICKET>_YYYYMMDD_HHmmss.html` |
| `Cowork-Daily-Briefing.md` | Pulls all assigned/unresolved Jira tickets and mentions; writes a prioritized daily briefing to markdown, then converts it to HTML | `data\Daily briefing\Reports\YYYY-MM-DD.html` |

### Jira triage task (`Cowork-Jira-Triage.md`)

- Reads a last-run timestamp from `jira_poll_state.txt`; aborts if fewer than 20 minutes have passed
- Runs two JQL queries: assigned tickets + SAGE engagement tickets updated since the last run
- Deduplicates and assesses each ticket for required SA action (reply, triage, discover, verify)
- Also scans unread Gmail (non-Jira, unlabelled) for actionable emails
- Generates one report per actionable item; filename encodes the action verb, ticket key, date, and time
- Action verbs: `Triage` · `Discover` · `Reply` · `Verify`

### Daily briefing task (`Cowork-Daily-Briefing.md`)

- Queries all assigned, unresolved tickets across SAGE and LIT projects; flags anything due this week or blocked
- Checks for mentions of the user in tickets not directly assigned
- Runs a secondary pass for callouts to "Tier1 Release Managers"
- Writes a prioritized briefing MD file named `YYYY-MM-DD.md`, converts it to HTML, and appends a line to `action_log.txt`
