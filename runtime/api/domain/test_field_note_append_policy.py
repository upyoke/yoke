"""Durable root grouping and independent field-note writes."""

from unittest.mock import patch

import pytest

from yoke_contracts.timestamps import utc_now
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.handlers import ouroboros_field_note as handler
from yoke_core.domain.ouroboros_entries import (
    count_entry_rows,
    get_entry_row,
    list_entry_rows,
)
from runtime.api.domain.test_ouroboros_field_note import (
    _build_request,
    _ok_emit_result,
)


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    from runtime.api.fixtures.file_test_db import init_test_db

    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


@pytest.fixture(autouse=True)
def no_telemetry():
    with patch.object(handler._events, "emit_event", return_value=_ok_emit_result()):
        yield


def append(body, *, session="session-a", root=None, **payload):
    request = _build_request(evidence=body, session_id=session, correlation_id=root)
    request.payload.update(payload)
    return handler.handle_append(request)


@pytest.mark.parametrize("bodies", [
    ("same evidence", "same evidence"),
    ("Missing   guidance", "missing\nguidance"),
    ("a" * 200 + " first", "a" * 200 + " second"),
])
def test_each_append_stores_its_own_note(tmp_db, bodies):
    with patch.object(handler, "utc_now", return_value=utc_now()):
        first, second = [append(body) for body in bodies]
    assert first.primary_success and second.primary_success
    assert first.result_payload["entry_id"] != second.result_payload["entry_id"]
    with connect() as conn:
        assert count_entry_rows(conn) == 2
        rows = conn.execute("SELECT session_id FROM ouroboros_entries").fetchall()
        assert [row[0] for row in rows] == ["session-a", "session-a"]


def test_correlated_repeat_survives_without_events_and_leaves_queue(tmp_db):
    root = append("first report").result_payload["entry_id"]
    with patch.object(
        handler._events, "emit_event", return_value=type("Result", (), {"ok": False})()
    ):
        repeat = append("more evidence of that same cause", root=root)
    assert repeat.primary_success
    assert repeat.result_payload["event_id"] is None
    child = int(repeat.result_payload["entry_id"])
    with connect() as conn:
        row = conn.execute(
            "SELECT correlation_id, session_id FROM ouroboros_entries WHERE id=%s",
            (child,),
        ).fetchone()
        assert tuple(row) == (int(root), "session-a")
        assert count_entry_rows(conn, unreviewed=True) == 1
        entries = list_entry_rows(conn, unreviewed=True)
        assert len(entries) == 1
        assert entries[0]["repeat_count"] == 1
        assert entries[0]["repeats"][0]["id"] == child
        assert get_entry_row(conn, child)["correlation_id"] == int(root)
    nested = append("third context", root=str(child))
    assert nested.result_payload["correlation_id"] == root


def test_session_can_store_many_notes(tmp_db):
    results = [append(f"distinct cause {i}") for i in range(25)]
    assert all(result.primary_success for result in results)
    assert len({result.result_payload["entry_id"] for result in results}) == 25
    with connect() as conn:
        assert count_entry_rows(conn) == 25


def test_correlation_rejects_missing_root_and_run_labels(tmp_db):
    for root in ("missing-run", "9999999"):
        result = append("evidence", root=root)
        assert not result.primary_success
        assert result.error.code == "field_note_correlation_invalid"
    with connect() as conn:
        assert count_entry_rows(conn) == 0


def test_project_isolation_and_roster_counts(test_db):
    from yoke_core.domain.ouroboros_entry_roster import list_roster_page
    from yoke_core.domain.project_identity import resolve_project_id

    from runtime.api.fixtures.backlog_insert_support import ensure_project_id

    ensure_project_id(test_db, "yoke", ts=utc_now())
    ensure_project_id(test_db, "other-notes", ts=utc_now())
    test_db.commit()
    first = append("shared body", project="yoke")
    other = append("shared body", project="other-notes")
    assert first.primary_success and other.primary_success
    assert first.result_payload["entry_id"] != other.result_payload["entry_id"]
    refused = append(
        "repeat", project="other-notes", root=first.result_payload["entry_id"]
    )
    assert refused.error.code == "field_note_correlation_invalid"
    child = append(
        "same cause in another context",
        project="yoke",
        root=first.result_payload["entry_id"],
    )
    page = list_roster_page(test_db, project="yoke", review_state="unreviewed")
    assert page["matching_count"] == 1
    assert page["entries"][0]["repeats"][0]["id"] == int(
        child.result_payload["entry_id"]
    )
    assert resolve_project_id(test_db, "other-notes")


def test_repeat_projection_is_bounded_and_retains_total(test_db):
    from yoke_core.domain.ouroboros_entries import cmd_insert_entry
    from runtime.api.fixtures.backlog_insert_support import ensure_project_id

    ensure_project_id(test_db, "yoke", ts=utc_now())
    test_db.commit()
    root = int(append("root problem", project="yoke").result_payload["entry_id"])
    for number in range(23):
        cmd_insert_entry(
            test_db,
            utc_now(),
            "tester",
            None,
            "observation",
            f"repeat context {number}",
            "yoke",
            correlation_id=root,
        )
    row = get_entry_row(test_db, root)
    assert row["repeat_count"] == 23
    assert len(row["repeats"]) == 20
    assert row["repeats"][0]["id"] > row["repeats"][-1]["id"]
