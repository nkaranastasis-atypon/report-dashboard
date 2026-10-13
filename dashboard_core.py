"""Shared parsing and database helpers for the dashboard and MCP server."""

import re
import sqlite3
from datetime import datetime
from pathlib import Path


DB_PATH = Path(__file__).parent / "dashboard_state.db"

_DATE8_RE = re.compile(r"^\d{8}$")
_TIME6_RE = re.compile(r"^\d{6}$")
_FOLDER_DATE_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")


def parse_date_folder(name: str) -> str:
    match = _FOLDER_DATE_RE.match(name)
    if match:
        try:
            return datetime(
                int(match.group(1)), int(match.group(2)), int(match.group(3))
            ).date().isoformat()
        except ValueError:
            pass
    return name


def parse_filename(name: str):
    """Return action, ticket, date, and time parsed from a report filename."""
    stem = name[:-5] if name.lower().endswith(".html") else name
    parts = stem.split("_")
    timestamp = None
    date = None

    if parts and _TIME6_RE.match(parts[-1]):
        timestamp = parts.pop()
    if parts and _DATE8_RE.match(parts[-1]):
        date = parts.pop()

    action = parts[0] if parts else None
    ticket = "_".join(parts[1:]) if len(parts) > 1 else None
    if ticket and ticket.upper().startswith("EMAIL_"):
        ticket = None

    file_ts = (
        f"{timestamp[:2]}:{timestamp[2:4]}:{timestamp[4:]}"
        if timestamp and len(timestamp) == 6
        else timestamp
    )
    file_date = (
        f"{date[:4]}-{date[4:6]}-{date[6:]}"
        if date and len(date) == 8
        else date
    )
    return action, ticket, file_date, file_ts


def connect_readonly(db_path: str | Path = DB_PATH) -> sqlite3.Connection:
    """Open a query-only SQLite connection without creating a missing database."""
    path = Path(db_path).resolve()
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection