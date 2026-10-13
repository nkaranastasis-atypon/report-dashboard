from pathlib import Path
import sqlite3

import pytest

import dashboard_core
import mcp_server
import server


@pytest.fixture
def dashboard(tmp_path, monkeypatch):
    db_path = tmp_path / "dashboard_state.db"
    triage_root = tmp_path / "ai-triage"
    briefings_root = tmp_path / "briefings"
    triage_root.mkdir()
    briefings_root.mkdir()
    monkeypatch.setattr(server, "DB_PATH", db_path)
    monkeypatch.setattr(
        mcp_server,
        "SETTINGS",
        mcp_server.Settings(db_path, triage_root, briefings_root),
    )
    server.init_db()

    def add_report(
        *,
        filename="Reply_SAGE-1_20261013_120000.html",
        action="Reply",
        ticket="SAGE-1",
        status="new",
        note="A note",
        path=None,
        file_date="2026-10-13",
        file_ts="12:00:00",
        date_folder="2026-10-13",
        first_seen_at=None,
    ):
        stored_path = path or f"Reports\\20261013\\{filename}"
        now = "2026-10-13T12:00:00+00:00"
        connection = server.get_db()
        try:
            cursor = connection.execute(
                """INSERT INTO reports
                   (path, date_folder, filename, action, ticket, file_date, file_ts,
                    status, note, detected_at, modified_at, first_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    stored_path,
                    date_folder,
                    filename,
                    action,
                    ticket,
                    file_date,
                    file_ts,
                    status,
                    note,
                    now,
                    now,
                    first_seen_at,
                ),
            )
            connection.commit()
            return cursor.lastrowid
        finally:
            connection.close()

    return {
        "db_path": db_path,
        "triage_root": triage_root,
        "briefings_root": briefings_root,
        "add_report": add_report,
    }


def add_event(report_id, event_type, detail, created_at):
    connection = server.get_db()
    try:
        connection.execute(
            "INSERT INTO events (report_id, event_type, detail, created_at) VALUES (?, ?, ?, ?)",
            (report_id, event_type, detail, created_at),
        )
        connection.commit()
    finally:
        connection.close()


def test_report_content_uses_markdown_then_html_fallback(dashboard):
    filename = "Reply_SAGE-1_20261013_120000.html"
    report_id = dashboard["add_report"](filename=filename)
    markdown_path = dashboard["triage_root"] / "20261013" / "Reply_SAGE-1_20261013_120000.md"
    html_path = dashboard["triage_root"] / "Reports" / "20261013" / filename
    markdown_path.parent.mkdir(parents=True)
    html_path.parent.mkdir(parents=True)
    markdown_path.write_text("markdown body", encoding="utf-8")
    html_path.write_text("<p>html body</p>", encoding="utf-8")

    result = mcp_server.get_report(report_id, max_chars=5)
    assert result["content"]["content_source"] == "md"
    assert result["content"]["content"] == "markd"
    assert result["content"]["content_length"] == len("markdown body")
    assert result["content"]["truncated"] is True

    markdown_path.unlink()
    result = mcp_server.get_report(report_id)
    assert result["content"]["content_source"] == "html"
    assert result["content"]["content"] == "html body"


def test_report_path_rejects_traversal(dashboard):
    row = {"path": r"Reports\..\..\outside.html"}
    with pytest.raises(ValueError, match="traversal"):
        mcp_server._report_file_paths(row)


def test_parser_handles_windows_paths_and_email_names():
    assert dashboard_core.parse_filename(
        "Reply_SAGE-7051_20260414_130239.html"
    ) == ("Reply", "SAGE-7051", "2026-04-14", "13:02:39")
    assert dashboard_core.parse_filename(
        "Reply_EMAIL_subject_words_20260414_130239.html"
    ) == ("Reply", None, "2026-04-14", "13:02:39")


def test_readonly_connection_rejects_writes(dashboard):
    connection = mcp_server.connect_readonly(dashboard["db_path"])
    try:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM reports")
    finally:
        connection.close()


def test_modified_events_are_not_returned_and_note_history_is_best_effort(dashboard):
    report_id = dashboard["add_report"](note="current note")
    add_event(report_id, "modified", "File updated", "2026-10-13T12:01:00+00:00")
    add_event(
        report_id,
        "status_change",
        "new → in_review | first | note",
        "2026-10-13T12:02:00+00:00",
    )
    add_event(
        report_id,
        "status_change",
        "in_review → done",
        "2026-10-13T12:03:00+00:00",
    )
    result = mcp_server.get_report(report_id)

    assert all(event["event_type"] != "modified" for event in result["events"])
    assert [entry["note"] for entry in result["note_history"]] == [
        "first | note",
        "current note",
    ]
    assert "notice" in result


def test_manual_task_returns_title_and_description_without_file_access(
    dashboard, monkeypatch
):
    report_id = dashboard["add_report"](
        filename="Follow up",
        action="TASK",
        ticket=None,
        note="Ask the team for an update",
        path="manual/task-id",
        file_date=None,
        file_ts=None,
    )
    monkeypatch.setattr(
        mcp_server,
        "_report_file_paths",
        lambda _row: pytest.fail("manual tasks must not resolve a file"),
    )

    result = mcp_server.get_report(report_id)
    assert result["title"] == "Follow up"
    assert result["description"] == "Ask the team for an update"
    assert result["note"] is None
    assert result["note_history"] == []
    assert result["content"]["content_source"] == "none"


def test_status_updates_preserve_omitted_notes_and_allow_explicit_clear(dashboard):
    single_id = dashboard["add_report"]()
    bulk_id = dashboard["add_report"](filename="Reply_SAGE-2_20261013_130000.html")

    server.update_status(single_id, server.StatusUpdate(status="done"))
    server.bulk_update(server.BulkUpdate(ids=[bulk_id], status="in_review"))
    connection = server.get_db()
    try:
        notes = [
            connection.execute("SELECT note FROM reports WHERE id=?", (report_id,)).fetchone()[0]
            for report_id in (single_id, bulk_id)
        ]
    finally:
        connection.close()
    assert notes == ["A note", "A note"]

    server.update_status(single_id, server.StatusUpdate(status="done", note=None))
    server.bulk_update(
        server.BulkUpdate(ids=[bulk_id], status="flagged", note="")
    )
    connection = server.get_db()
    try:
        notes = [
            connection.execute("SELECT note FROM reports WHERE id=?", (report_id,)).fetchone()[0]
            for report_id in (single_id, bulk_id)
        ]
    finally:
        connection.close()
    assert notes == [None, ""]


def test_list_reports_combines_filters_and_limits_page(dashboard):
    dashboard["add_report"](ticket="SAGE-1", note="keep this note")
    dashboard["add_report"](
        filename="Reply_SAGE-2_20261012_120000.html",
        ticket="SAGE-2",
        note=None,
        date_folder="2026-10-12",
        file_date="2026-10-12",
    )
    result = mcp_server.list_reports(
        has_note=False, since="2026-10-12", until="2026-10-13", limit=1
    )
    assert result["total"] == 1
    assert len(result["items"]) == 1
    assert result["items"][0]["ticket"] == "SAGE-2"


def test_ticket_context_and_open_items_use_per_report_status(dashboard):
    older_id = dashboard["add_report"](status="flagged")
    dashboard["add_report"](
        filename="Reply_SAGE-1_20261014_120000.html",
        status="done",
        file_date="2026-10-14",
        date_folder="2026-10-14",
    )
    context = mcp_server.get_ticket_context("sage-1")
    opened = mcp_server.get_open_items()
    assert len(context["reports"]) == 2
    assert context["latest_status"] == "done"
    assert opened["open_report_count"] == 1
    assert opened["tickets"][0]["latest_report"]["id"] == older_id


def test_briefing_latest_and_html_text(dashboard):
    html_path = dashboard["briefings_root"] / "Reports" / "2026-10-13.html"
    html_path.parent.mkdir()
    html_path.write_text(
        "<style>hidden</style><h1>Daily</h1><p>SAGE-1</p>", encoding="utf-8"
    )
    result = mcp_server.get_briefing("latest")
    assert result["date"] == "2026-10-13"
    assert result["content_source"] == "html"
    assert result["content"] == "Daily\nSAGE-1"


def test_content_search_ticket_briefing_and_stats(dashboard):
    report_id = dashboard["add_report"](status="done", note="Resolved")
    report_dir = dashboard["triage_root"] / "20261013"
    report_dir.mkdir()
    (report_dir / "Reply_SAGE-1_20261013_120000.md").write_text(
        "Needle in report content", encoding="utf-8"
    )
    (dashboard["briefings_root"] / "2026-10-13.md").write_text(
        "SAGE-1 was discussed", encoding="utf-8"
    )

    search = mcp_server.search_report_content("needle")
    context = mcp_server.get_ticket_context("SAGE-1")
    briefing_dates = mcp_server.list_briefings(since="2026-10-13")
    stats = mcp_server.get_dashboard_stats()

    assert search["results"][0]["id"] == report_id
    assert context["briefing_dates"] == ["2026-10-13"]
    assert briefing_dates["dates"] == ["2026-10-13"]
    assert stats["status_counts"] == {"done": 1}
    assert stats["top_tickets"][0]["done_ratio"] == 1.0
    assert all("notice" in response for response in (search, context, briefing_dates, stats))