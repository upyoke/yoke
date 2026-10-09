"""Epic and section owners bind native clocks and format only their views."""

import io
from datetime import datetime, timedelta

import pytest

from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant
from yoke_core.domain import (
    epic_cascade,
    epic_dispatch,
    epic_review,
    item_status_transitions,
    sections,
)
from yoke_core.domain.epic_resolution import dispatch_chain_get
from yoke_core.domain.epic_task_crud import task_update_field
from yoke_core.domain.epic_submission_receipt import submission_receipt_get
from yoke_core.domain.sections_cli import cmd_list


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_dispatch_progress_cascade_and_sections_keep_native_microseconds(
    test_db, monkeypatch, zone
):
    from runtime.api.fixtures.backlog_inserts import insert_epic_task, insert_item
    from runtime.api.test_epic_submission_receipt import RECEIPT
    from yoke_core.domain.epic_task_scope import set_no_files_scope
    from yoke_core.domain.project_identity import render_item_ref

    test_db.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    anchor = parse_instant("1969-12-31T23:59:59.999999Z")
    insert_item(test_db, id=42, workflow_id="epic", status="planned")
    for number in [1, 2]:
        insert_epic_task(
            test_db,
            epic_id=42,
            task_num=number,
            title="Native clock",
            status="planning",
        )
        set_no_files_scope(test_db, 42, number)
    monkeypatch.setattr(epic_dispatch, "utc_now", lambda: anchor)
    epic_dispatch.dispatch_chain_upsert(
        test_db,
        "42",
        "native-clock",
        {
            "queue": [1, 2],
            "current_task": "1",
            "current_attempt": 3,
            "started_at": "1969-12-31T18:59:59.999999-05:00",
        },
    )
    row = test_db.execute(
        "SELECT started_at,last_updated,current_attempt FROM epic_dispatch_chains WHERE epic_id=42"
    ).fetchone()
    assert row["started_at"] == row["last_updated"] == anchor
    assert row["current_attempt"] == 3
    assert (
        dispatch_chain_get(test_db, "42", "native-clock").split("|")[-2:]
        == [format_instant(anchor)] * 2
    )
    epic_dispatch.dispatch_chain_update(
        test_db, "42", "native-clock", "started_at", None
    )
    assert dispatch_chain_get(test_db, "42", "native-clock").split("|")[-2] == ""
    next_clock = anchor + timedelta(microseconds=1)
    monkeypatch.setattr(epic_dispatch, "utc_now", lambda: next_clock)
    assert epic_dispatch.dispatch_chain_advance(test_db, "42", "native-clock") == "1|2"
    row = test_db.execute(
        "SELECT started_at,last_updated,current_attempt FROM epic_dispatch_chains WHERE epic_id=42"
    ).fetchone()
    assert row["started_at"] is None
    assert row["last_updated"] == next_clock
    assert row["current_attempt"] == 3
    epic_dispatch.dispatch_chain_update(
        test_db, "42", "native-clock", "last_updated", None
    )
    assert dispatch_chain_get(test_db, "42", "native-clock").split("|")[-1] == ""
    monkeypatch.setattr(epic_review, "utc_now", lambda: anchor)
    epic_review.progress_note_insert(test_db, "42", 1, 1, RECEIPT, "opaque-commit")
    assert (
        test_db.execute(
            "SELECT created_at FROM epic_progress_notes WHERE epic_id=42"
        ).fetchone()[0]
        == anchor
    )
    receipt = submission_receipt_get(test_db, "42", 1)
    assert receipt.split("|")[5] == format_instant(anchor)
    assert (
        test_db.execute(
            "SELECT body FROM epic_progress_notes WHERE epic_id=42"
        ).fetchone()[0]
        == RECEIPT
    )
    monkeypatch.setattr(epic_cascade, "utc_now", lambda: anchor)
    monkeypatch.setattr(item_status_transitions, "utc_now", lambda: anchor)
    events = []
    monkeypatch.setattr(
        epic_cascade, "emit_event", lambda name, **kw: events.append((name, kw))
    )
    assert (
        epic_cascade.cascade_task_status(test_db, "42", "planning", "plan-drafted")
        == "2"
    )
    assert [
        row[0]
        for row in test_db.execute(
            "SELECT last_heartbeat FROM epic_tasks WHERE epic_id=42 ORDER BY task_num"
        ).fetchall()
    ] == [anchor, anchor]
    transitions = test_db.execute(
        "SELECT created_at FROM item_status_transitions WHERE item_id=42 AND task_num IS NOT NULL"
    ).fetchall()
    assert len(transitions) == 2
    assert all(row[0] == anchor for row in transitions)
    assert len(events) == 2
    assert all(
        kw["created_at"] == anchor
        and kw["conn"] is test_db
        and kw["transactional"] is True
        for _, kw in events
    )

    class Borrowed:
        def __getattr__(self, name):
            return getattr(test_db, name)

        def close(self):
            pass

    monkeypatch.setattr(sections.db_helpers, "connect", lambda *args, **kw: Borrowed())
    monkeypatch.setattr(sections, "utc_now", lambda: anchor)
    sections.upsert_section(
        42, "Native clock", "opaque 1969-12-31", ordering=123, source="operator"
    )
    monkeypatch.setattr(sections, "utc_now", lambda: next_clock)
    sections.upsert_section(42, "Native clock", "unchanged clock body")
    [(_, ordering, created, updated)] = [
        row for row in sections.list_sections(42) if row[0] == "Native clock"
    ]
    assert ordering == "123"
    assert created == anchor and updated == next_clock
    assert isinstance(created, datetime) and isinstance(updated, datetime)
    output = io.StringIO()
    assert cmd_list([render_item_ref(test_db, 42)], out=output) == 0
    assert (
        f"Native clock|123|{format_instant(anchor)}|{format_instant(next_clock)}"
        in output.getvalue()
    )


@pytest.mark.parametrize(
    "bad", ["", "1969-12-31", "1969-12-31T23:59:59", datetime(1969, 12, 31)]
)
def test_invalid_epic_clocks_refuse_before_any_scope_lane_or_activity_write(bad):
    class NoSQL:
        def execute(self, *args, **kwargs):
            raise AssertionError("invalid clock must refuse before SQL")

    for operation in [
        lambda: epic_dispatch.dispatch_chain_upsert(
            NoSQL(), "42", "native-clock", {"started_at": bad}
        ),
        lambda: epic_dispatch.dispatch_chain_update(
            NoSQL(), "42", "native-clock", "last_updated", bad
        ),
        lambda: task_update_field(NoSQL(), "42", 1, "last_heartbeat", bad),
    ]:
        with pytest.raises(InvalidInstant, match="invalid_instant"):
            operation()
