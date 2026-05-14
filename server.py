"""
Report Dashboard — server.py
============================
Watches a Reports folder with the structure:
    <root>/YYYYMMDD/action_ticket_timestamp.html

Parses filenames into structured fields (action, ticket, time),
stores state in SQLite, serves a REST API for the dashboard UI.

Default reports dir:  %userprofile%\\Documents\\Claude\\ai-triage
Default port       : 8765

Usage:
    pip install fastapi uvicorn watchdog
    python server.py
    python server.py --reports-dir "C:\\path\\to\\folder"
    python server.py --port 9000
"""

import argparse
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# ---------------------------------------------------------------------------
# Filename / folder parser
# ---------------------------------------------------------------------------
# Folder name:   YYYYMMDD  →  parsed to ISO date YYYY-MM-DD
#
# Filename convention (actual):
#   action_ticket_YYYYMMDD_HHMMSS.html   e.g. Triage_SAGE-8209_20260401_165838.html
#   action_ticket_HHMMSS.html            (older: no embedded date)
#   action_YYYYMMDD_HHMMSS.html          (no ticket)
#   action_HHMMSS.html                   (no ticket, no date)
#   anything.html                        (fallback)
#
# Strategy: split on '_', then peel known segments off the RIGHT end:
#   - 6-digit trailing segment  → time  (HHMMSS)
#   - 8-digit next segment      → date  (YYYYMMDD)
#   - first remaining segment   → action
#   - everything between        → ticket

_DATE8_RE = re.compile(r'^\d{8}$')
_TIME6_RE = re.compile(r'^\d{6}$')
_FOLDER_DATE_RE = re.compile(r'^(\d{4})(\d{2})(\d{2})$')


def parse_date_folder(name: str) -> str:
    m = _FOLDER_DATE_RE.match(name)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date().isoformat()
        except ValueError:
            pass
    return name  # non-date folder: return as-is


def parse_filename(name: str):
    """Return (action, ticket, file_date, file_ts) parsed from a report filename.

    All four fields may be None if not present/parseable.
    """
    stem  = name[:-5] if name.lower().endswith('.html') else name
    parts = stem.split('_')

    ts_raw   = None
    date_raw = None

    # Peel time (6 digits) off the right
    if parts and _TIME6_RE.match(parts[-1]):
        ts_raw = parts.pop()

    # Peel date (8 digits) off the right
    if parts and _DATE8_RE.match(parts[-1]):
        date_raw = parts.pop()

    action = parts[0] if parts else None
    ticket = '_'.join(parts[1:]) if len(parts) > 1 else None

    # Format HHMMSS → HH:MM:SS
    file_ts = (f"{ts_raw[:2]}:{ts_raw[2:4]}:{ts_raw[4:]}"
               if ts_raw and len(ts_raw) == 6 else ts_raw)

    # Format YYYYMMDD → YYYY-MM-DD
    file_date = (f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:]}"
                 if date_raw and len(date_raw) == 8 else date_raw)

    return action, ticket, file_date, file_ts


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DB_PATH    = Path(__file__).parent / "dashboard_state.db"
STATIC_DIR = Path(__file__).parent / "static"

_db_lock = threading.Lock()


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS reports (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            path         TEXT UNIQUE NOT NULL,
            date_folder  TEXT NOT NULL,
            filename     TEXT NOT NULL,
            action       TEXT,
            ticket       TEXT,
            file_date    TEXT,
            file_ts      TEXT,
            size_bytes   INTEGER NOT NULL DEFAULT 0,
            status       TEXT NOT NULL DEFAULT 'new',
            note         TEXT,
            detected_at  TEXT NOT NULL,
            modified_at  TEXT NOT NULL,
            actioned_at  TEXT,
            first_seen_at TEXT
        );

        CREATE TABLE IF NOT EXISTS events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id   INTEGER NOT NULL,
            event_type  TEXT NOT NULL,
            detail      TEXT,
            created_at  TEXT NOT NULL,
            FOREIGN KEY (report_id) REFERENCES reports(id)
        );

        CREATE INDEX IF NOT EXISTS idx_status      ON reports(status);
        CREATE INDEX IF NOT EXISTS idx_date_folder ON reports(date_folder);
        CREATE INDEX IF NOT EXISTS idx_action      ON reports(action);
        CREATE INDEX IF NOT EXISTS idx_events      ON events(report_id);
    """)
    conn.commit()
    # Migration: add first_seen_at to existing databases that predate this column
    try:
        conn.execute("ALTER TABLE reports ADD COLUMN first_seen_at TEXT")
        conn.commit()
    except Exception:
        pass  # column already exists - safe to ignore
    # Migration: add details_url for manually-created tasks
    try:
        conn.execute("ALTER TABLE reports ADD COLUMN details_url TEXT")
        conn.commit()
    except Exception:
        pass  # column already exists - safe to ignore
    conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_report(path: Path, reports_dir: Path):
    """Insert or update a report record; skip non-HTML files."""
    if path.suffix.lower() != '.html':
        return

    rel    = path.relative_to(reports_dir)
    parts  = list(rel.parts)

    # We expect at least one folder level: YYYYMMDD/filename.html
    filename    = parts[-1]
    folder_name = parts[-2] if len(parts) >= 2 else ""

    date_folder                          = parse_date_folder(folder_name)
    action, ticket, file_date, file_ts   = parse_filename(filename)
    size                                 = path.stat().st_size if path.exists() else 0
    now                                  = _now()

    with _db_lock:
        conn = get_db()
        try:
            existing = conn.execute(
                "SELECT id, status FROM reports WHERE path = ?", (str(rel),)
            ).fetchone()

            if existing:
                conn.execute(
                    "UPDATE reports SET size_bytes=?, modified_at=?, action=?, ticket=?, file_date=?, file_ts=? WHERE path=?",
                    (size, now, action, ticket, file_date, file_ts, str(rel))
                )
                conn.execute(
                    "INSERT INTO events (report_id, event_type, detail, created_at) VALUES (?,?,?,?)",
                    (existing["id"], "modified", f"File updated — {size} bytes", now)
                )
            else:
                cur = conn.execute(
                    """INSERT INTO reports
                       (path, date_folder, filename, action, ticket, file_date, file_ts,
                        size_bytes, status, detected_at, modified_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (str(rel), date_folder, filename, action, ticket, file_date, file_ts,
                     size, "new", now, now)
                )
                conn.execute(
                    "INSERT INTO events (report_id, event_type, detail, created_at) VALUES (?,?,?,?)",
                    (cur.lastrowid, "detected", f"Discovered: {filename}", now)
                )
            conn.commit()
        finally:
            conn.close()


def scan_directory(reports_dir: Path) -> int:
    count = 0
    for p in sorted(reports_dir.rglob("*.html")):
        if p.is_file():
            upsert_report(p, reports_dir)
            count += 1
    return count


# ---------------------------------------------------------------------------
# File watcher
# ---------------------------------------------------------------------------
class ReportHandler(FileSystemEventHandler):
    def __init__(self, reports_dir: Path):
        self.reports_dir = reports_dir

    def _handle(self, src: str):
        p = Path(src)
        if p.is_file() and p.suffix.lower() == ".html":
            upsert_report(p, self.reports_dir)

    def on_created(self, event):
        if not event.is_directory:
            self._handle(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._handle(event.src_path)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Report Dashboard", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

reports_dir_global: Path = Path("./Reports")
briefings_dir_global: Path = Path(".")

VALID_STATUSES = {"new", "in_review", "done", "canceled", "flagged"}


# ── Pydantic models ──────────────────────────────────────────────────────────

class StatusUpdate(BaseModel):
    status: str
    note: Optional[str] = None


class BulkUpdate(BaseModel):
    ids: list[int]
    status: str
    note: Optional[str] = None


class ManualTaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    ticket: Optional[str] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    ticket: Optional[str] = None


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.post("/api/manual", status_code=201)
def create_manual_task(body: ManualTaskCreate):
    """Create a manually-entered task (stored in DB only, not on disk)."""
    body.title = body.title.strip()
    if not body.title:
        raise HTTPException(422, "title must not be empty")
    now = _now()
    today = datetime.now().date().isoformat()
    path = f"manual/{uuid.uuid4().hex}"
    with _db_lock:
        conn = get_db()
        try:
            cur = conn.execute(
                """INSERT INTO reports
                   (path, date_folder, filename, action, ticket, file_date, file_ts,
                    size_bytes, status, note, details_url, detected_at, modified_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (path, today, body.title, "TASK", body.ticket or None, None, None,
                 0, "new", body.description, None, now, now)
            )
            rid = cur.lastrowid
            conn.execute(
                "INSERT INTO events (report_id, event_type, detail, created_at) VALUES (?,?,?,?)",
                (rid, "detected", f"Manual task created: {body.title}", now)
            )
            conn.commit()
            row = conn.execute("SELECT * FROM reports WHERE id=?", (rid,)).fetchone()
            return dict(row)
        finally:
            conn.close()


@app.patch("/api/manual/{report_id}")
def update_manual_task(report_id: int, body: TaskUpdate):
    """Update title and/or ticket of a manually-created task."""
    now = _now()
    with _db_lock:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT filename, ticket, action FROM reports WHERE id=?", (report_id,)
            ).fetchone()
            if not row:
                raise HTTPException(404, "Not found")
            if row["action"] != "TASK":
                raise HTTPException(400, "Only manual tasks can be edited via this endpoint")
            new_title  = body.title.strip()  if body.title  is not None else row["filename"]
            new_ticket = body.ticket.strip() if body.ticket is not None else row["ticket"]
            if not new_title:
                raise HTTPException(422, "title must not be empty")
            changes = []
            if new_title  != row["filename"]: changes.append(f"title: {row['filename']} → {new_title}")
            if new_ticket != row["ticket"]:   changes.append(f"ticket: {row['ticket'] or '—'} → {new_ticket or '—'}")
            conn.execute(
                "UPDATE reports SET filename=?, ticket=?, modified_at=? WHERE id=?",
                (new_title, new_ticket or None, now, report_id)
            )
            if changes:
                conn.execute(
                    "INSERT INTO events (report_id, event_type, detail, created_at) VALUES (?,?,?,?)",
                    (report_id, "modified", "; ".join(changes), now)
                )
            conn.commit()
            row = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
            return dict(row)
        finally:
            conn.close()


@app.get("/api/reports")
def list_reports(
    status:      Optional[str] = Query(None),
    date_folder: Optional[str] = Query(None),
    action:      Optional[str] = Query(None),
    ticket:      Optional[str] = Query(None),
    search:      Optional[str] = Query(None),
    sort:  str  = Query("date_folder"),
    order: str  = Query("desc"),
    limit: int  = Query(100),
    offset: int = Query(0),
):
    where, params = [], []
    if status:      where.append("status = ?");       params.append(status)
    if date_folder: where.append("date_folder = ?");  params.append(date_folder)
    if action:      where.append("action = ?");       params.append(action)
    if ticket:      where.append("ticket LIKE ?");    params.append(f"%{ticket}%")
    if search:
        where.append("(filename LIKE ? OR action LIKE ? OR ticket LIKE ? OR note LIKE ?)")
        s = f"%{search}%"; params.extend([s, s, s, s])

    w  = ("WHERE " + " AND ".join(where)) if where else ""
    ok = {"date_folder","filename","action","ticket","size_bytes",
          "status","detected_at","modified_at","actioned_at","file_ts","file_date"}
    sc = sort if sort in ok else "date_folder"
    od = "DESC" if order.lower() == "desc" else "ASC"

    conn = get_db()
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM reports {w}", params).fetchone()[0]
        rows  = conn.execute(
            f"SELECT * FROM reports {w} ORDER BY {sc} {od}, file_ts {od} LIMIT ? OFFSET ?",
            params + [limit, offset]
        ).fetchall()
        return {"total": total, "items": [dict(r) for r in rows]}
    finally:
        conn.close()


@app.get("/api/reports/{report_id}")
def get_report(report_id: int):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Not found")
        events = conn.execute(
            "SELECT * FROM events WHERE report_id = ? ORDER BY created_at DESC",
            (report_id,)
        ).fetchall()
        return {**dict(row), "events": [dict(e) for e in events]}
    finally:
        conn.close()


@app.post("/api/reports/{report_id}/mark-seen")
def mark_seen(report_id: int):
    """Record the first time a report is opened - clears the 'unseen' highlight."""
    now = _now()
    with _db_lock:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT first_seen_at FROM reports WHERE id = ?", (report_id,)
            ).fetchone()
            if not row:
                raise HTTPException(404, "Not found")
            if row["first_seen_at"] is None:
                conn.execute(
                    "UPDATE reports SET first_seen_at = ? WHERE id = ?", (now, report_id)
                )
                conn.commit()
            return {"ok": True, "first_seen_at": row["first_seen_at"] or now}
        finally:
            conn.close()

@app.get("/api/reports/{report_id}/preview", response_class=HTMLResponse)
def preview_report(report_id: int):
    """Serve the raw HTML file for sandboxed iframe rendering."""
    conn = get_db()
    try:
        row = conn.execute("SELECT path, action FROM reports WHERE id = ?", (report_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Not found")
        if row["action"] == "TASK":
            raise HTTPException(404, "Manual tasks have no file preview")
        full_path = reports_dir_global / row["path"]
        if not full_path.exists():
            return HTMLResponse(
                "<p style='font-family:monospace;padding:2rem;color:#666'>File not found on disk.</p>"
            )
        content = full_path.read_text(encoding="utf-8", errors="replace")

        # Inject a style override just before </head> (or at the top if no <head>)
        INJECT = """
<style>
  html, body {
    margin: 12px 0 !important;
    padding: 0 12px !important;
    background: #1a1f2e !important;
    color: #c8d8f0 !important;
  }
  a { color: #6aa3e8 !important; }
  h1, h2, h3, h4 { color: #d4e4f7 !important; }
  table { border-color: #2e3a50 !important; }
  th { background: #1f2836 !important; color: #8ca8c8 !important; }
  td { border-color: #2e3a50 !important; }
  pre, code { background: #0d1017 !important; color: #a8c8a0 !important; }
  tr:nth-child(even) { background: #1a2233 !important; }
  tr:nth-child(odd)  { background: #1a1f2e !important; }
  blockquote {color: #9E9Cb3 !important; }
  .card { background:none !important; font-size: 15px !important; }
</style>
"""
        if "</head>" in content:
            content = content.replace("</head>", INJECT + "</head>", 1)
        elif "<body" in content:
            # inject right after opening body tag
            import re
            content = re.sub(r'(<body[^>]*>)', r'\1' + INJECT, content, count=1)
        else:
            content = INJECT + content

        return HTMLResponse(content)
    finally:
        conn.close()


@app.patch("/api/reports/{report_id}/status")
def update_status(report_id: int, body: StatusUpdate):
    if body.status not in VALID_STATUSES:
        raise HTTPException(400, f"status must be one of {VALID_STATUSES}")
    now = _now()
    with _db_lock:
        conn = get_db()
        try:
            row = conn.execute("SELECT status FROM reports WHERE id=?", (report_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Not found")
            old = row["status"]
            conn.execute(
                "UPDATE reports SET status=?, note=?, actioned_at=? WHERE id=?",
                (body.status, body.note, now, report_id)
            )
            conn.execute(
                "INSERT INTO events (report_id, event_type, detail, created_at) VALUES (?,?,?,?)",
                (report_id, "status_change",
                 f"{old} → {body.status}" + (f" | {body.note}" if body.note else ""), now)
            )
            conn.commit()
            return {"ok": True, "id": report_id, "status": body.status}
        finally:
            conn.close()


@app.post("/api/reports/bulk-status")
def bulk_update(body: BulkUpdate):
    if body.status not in VALID_STATUSES:
        raise HTTPException(400, "Invalid status")
    now = _now()
    updated = 0
    with _db_lock:
        conn = get_db()
        try:
            for rid in body.ids:
                row = conn.execute("SELECT status FROM reports WHERE id=?", (rid,)).fetchone()
                if row:
                    conn.execute(
                        "UPDATE reports SET status=?, note=?, actioned_at=? WHERE id=?",
                        (body.status, body.note, now, rid)
                    )
                    conn.execute(
                        "INSERT INTO events (report_id, event_type, detail, created_at) VALUES (?,?,?,?)",
                        (rid, "status_change", f"bulk → {body.status}", now)
                    )
                    updated += 1
            conn.commit()
            return {"ok": True, "updated": updated}
        finally:
            conn.close()


@app.get("/api/stats")
def get_stats():
    conn = get_db()
    try:
        status_counts = {
            r["status"]: r["cnt"]
            for r in conn.execute(
                "SELECT status, COUNT(*) as cnt FROM reports GROUP BY status"
            ).fetchall()
        }
        actions = [dict(r) for r in conn.execute(
            "SELECT action, COUNT(*) as cnt FROM reports WHERE action IS NOT NULL "
            "GROUP BY action ORDER BY cnt DESC LIMIT 20"
        ).fetchall()]
        dates = [dict(r) for r in conn.execute(
            "SELECT date_folder, COUNT(*) as cnt FROM reports "
            "GROUP BY date_folder ORDER BY date_folder DESC LIMIT 60"
        ).fetchall()]
        tickets = [dict(r) for r in conn.execute(
            """SELECT ticket, COUNT(*) as cnt,
               SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) as done
               FROM reports WHERE ticket IS NOT NULL
               GROUP BY ticket ORDER BY cnt DESC LIMIT 20"""
        ).fetchall()]
        activity = [dict(r) for r in conn.execute(
            """SELECT e.*, r.filename, r.action, r.ticket
               FROM events e JOIN reports r ON r.id = e.report_id
               ORDER BY e.created_at DESC LIMIT 40"""
        ).fetchall()]
        total      = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        total_size = conn.execute("SELECT SUM(size_bytes) FROM reports").fetchone()[0] or 0
        return {
            "status_counts": status_counts,
            "actions": actions,
            "dates": dates,
            "tickets": tickets,
            "recent_activity": activity,
            "total": total,
            "total_size_bytes": total_size,
        }
    finally:
        conn.close()


@app.get("/api/meta")
def get_meta():
    """Distinct values for filter dropdowns."""
    conn = get_db()
    try:
        actions = [r[0] for r in conn.execute(
            "SELECT DISTINCT action FROM reports WHERE action IS NOT NULL ORDER BY action"
        ).fetchall()]
        date_folders = [r[0] for r in conn.execute(
            "SELECT DISTINCT date_folder FROM reports ORDER BY date_folder DESC"
        ).fetchall()]
        return {"actions": actions, "date_folders": date_folders}
    finally:
        conn.close()


@app.post("/api/scan")
def trigger_scan():
    count = scan_directory(reports_dir_global)
    return {"ok": True, "scanned": count}


@app.get("/api/briefings")
def list_briefings():
    """List available daily briefing HTML files (YYYY-MM-DD.html)."""
    if not briefings_dir_global.exists():
        return {"items": []}
    items = []
    for f in sorted(briefings_dir_global.glob("*.html"), reverse=True):
        # Only include files whose stem is a valid YYYY-MM-DD date
        if re.match(r'^\d{4}-\d{2}-\d{2}$', f.stem):
            items.append({"date": f.stem, "filename": f.name, "size_bytes": f.stat().st_size})
    return {"items": items}


@app.get("/api/briefings/{date}", response_class=HTMLResponse)
def get_briefing(date: str):
    """Serve a daily briefing HTML file as-is (no path traversal possible)."""
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date):
        raise HTTPException(400, "Invalid date format — expected YYYY-MM-DD")
    target = (briefings_dir_global / f"{date}.html").resolve()
    # Guard against path traversal
    if not str(target).startswith(str(briefings_dir_global.resolve())):
        raise HTTPException(400, "Invalid path")
    if not target.exists():
        raise HTTPException(404, "Briefing not found")
    content = target.read_text(encoding="utf-8", errors="replace")

    INJECT = """
<style>
  html, body {
    margin: 12px 0 !important;
    padding: 0 12px !important;
    background: #1a1f2e !important;
    color: #c8d8f0 !important;
  }
  a { color: #6aa3e8 !important; }
  h1, h2, h3, h4 { color: #d4e4f7 !important; }
  table { border-color: #2e3a50 !important; }
  th { background: #1f2836 !important; color: #8ca8c8 !important; }
  td { border-color: #2e3a50 !important; }
  pre, code { background: #0d1017 !important; color: #a8c8a0 !important; }
  tr:nth-child(even) { background: #1a2233 !important; }
  tr:nth-child(odd)  { background: #1a1f2e !important; }
  .card { background:none !important; font-size: 15px !important; }
</style>
"""
    if "</head>" in content:
        content = content.replace("</head>", INJECT + "</head>", 1)
    elif "<body" in content:
        content = re.sub(r'(<body[^>]*>)', r'\1' + INJECT, content, count=1)
    else:
        content = INJECT + content

    return HTMLResponse(content)


@app.get("/", response_class=FileResponse)
def serve_index():
    return FileResponse(str(STATIC_DIR / "index.html"))


# Serve static files (CSS, JS if ever split out)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
DEFAULT_REPORTS_DIR   = r" %userprofile%\Documents\Claude\ai-triage"
DEFAULT_BRIEFINGS_DIR = r" %userprofile%\Documents\Claude\Daily briefing\Reports"


def main():
    global reports_dir_global, briefings_dir_global

    parser = argparse.ArgumentParser(description="Report Dashboard v2")
    parser.add_argument(
        "--reports-dir",
        default=DEFAULT_REPORTS_DIR,
        help=f"Root reports folder (default: {DEFAULT_REPORTS_DIR})"
    )
    parser.add_argument(
        "--briefings-dir",
        default=DEFAULT_BRIEFINGS_DIR,
        help=f"Daily briefings folder (default: {DEFAULT_BRIEFINGS_DIR})"
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    reports_dir_global   = Path(args.reports_dir).resolve()
    briefings_dir_global = Path(args.briefings_dir).resolve()
    reports_dir_global.mkdir(parents=True, exist_ok=True)

    print(f"\n  Report Dashboard v2")
    print(f"  {'─'*50}")
    print(f"  Watching : {reports_dir_global}")
    print(f"  Briefings: {briefings_dir_global}")
    print(f"  Database : {DB_PATH}")

    init_db()
    count = scan_directory(reports_dir_global)
    print(f"  Scanned  : {count} HTML report(s) found")

    handler  = ReportHandler(reports_dir_global)
    observer = Observer()
    observer.schedule(handler, str(reports_dir_global), recursive=True)
    observer.start()
    print(f"  Watcher  : active")
    print(f"\n  → Open http://{args.host}:{args.port}\n")

    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    finally:
        observer.stop()
        observer.join()


if __name__ == "__main__":
    main()
