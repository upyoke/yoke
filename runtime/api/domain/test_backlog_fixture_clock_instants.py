"""Fixture writers bind declared instants and preserve opaque evidence."""

from datetime import datetime, timedelta
import sqlite3

import pytest

from yoke_contracts.timestamps import InvalidInstant, parse_instant
from runtime.api.fixtures import backlog_insert_support as support
from runtime.api.fixtures.backlog_inserts import (
    insert_deployment_run,
    insert_epic_task,
    insert_event,
    insert_item,
    insert_item_worktree,
)
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement, insert_qa_run

MOMENT = parse_instant("2026-10-09T16:11:12.345678+05:45")
OPAQUE = "captured 2026-10-09 10:26:12+00:00"


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_backlog_fixture_graph_retains_native_clocks_and_opaque_evidence(
    test_db, monkeypatch, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    monkeypatch.setattr(support, "utc_now", lambda: MOMENT)
    later = MOMENT + timedelta(microseconds=1)
    item = insert_item(
        test_db,
        id=7,
        project_sequence=7,
        workflow_id="dash",
        status="implementing",
        updated_at=later,
        spec=OPAQUE,
        merged_at=None,
    )
    assert item["created_at"] == MOMENT and isinstance(item["created_at"], datetime)
    assert item["updated_at"] == later and item["merged_at"] is None
    assert item["spec"] == OPAQUE
    lane = insert_item_worktree(
        test_db,
        item_id=7,
        branch="clock-proof",
        path="/tmp/clock-proof",
        updated_at=later,
        released_at=None,
    )
    assert lane["created_at"] == MOMENT and lane["updated_at"] == later
    assert lane["released_at"] is None
    task = insert_epic_task(
        test_db,
        epic_id=7,
        task_num=1,
        last_heartbeat=later,
        last_activity_at=None,
        body=OPAQUE,
    )
    assert task["last_heartbeat"] == later and task["last_activity_at"] is None
    assert task["body"] == OPAQUE
    event = insert_event(test_db, event_id="clock-proof-event", envelope=None)
    assert event["created_at"] == MOMENT
    run = insert_deployment_run(
        test_db, id="clock-proof-run", started_at=later, completed_at=None
    )
    assert run["created_at"] == MOMENT and run["started_at"] == later
    assert run["completed_at"] is None
    req = insert_qa_requirement(test_db, item_id=7)
    execution = insert_qa_run(
        test_db,
        qa_requirement_id=req["id"],
        started_at=later,
        completed_at=None,
        raw_result=OPAQUE,
    )
    assert req["created_at"] == MOMENT
    assert execution["created_at"] == MOMENT and execution["started_at"] == later
    assert execution["completed_at"] is None and execution["raw_result"] == OPAQUE


@pytest.mark.parametrize(
    "writer,kwargs",
    [
        (insert_item, {"created_at": ""}),
        (insert_item, {"updated_at": "2026-10-09"}),
        (insert_item, {"merged_at": "2026-10-09T10:26:12"}),
        (
            insert_item_worktree,
            {"item_id": 7, "branch": "clock-proof", "created_at": ""},
        ),
        (insert_epic_task, {"last_activity_at": MOMENT.replace(tzinfo=None)}),
        (insert_event, {"created_at": "2026-10-09"}),
        (insert_deployment_run, {"started_at": ""}),
        (insert_qa_requirement, {"created_at": ""}),
        (insert_qa_run, {"started_at": "2026-10-09T10:26:12"}),
    ],
)
def test_malformed_fixture_clock_refuses_before_any_insert(writer, kwargs):
    with pytest.raises(InvalidInstant):
        writer(object(), **kwargs)


def test_fixture_default_generator_rejects_naive_clock_before_sql(monkeypatch):
    monkeypatch.setattr(support, "utc_now", lambda: MOMENT.replace(tzinfo=None))
    with pytest.raises(InvalidInstant):
        insert_item(object())


def test_explicit_sqlite_values_format_only_known_clock_fields():
    with sqlite3.connect(":memory:") as conn:
        assert support.values(
            conn,
            "qa_runs",
            {
                "started_at": MOMENT,
                "completed_at": None,
                "raw_result": OPAQUE,
            },
        ) == ("2026-10-09T10:26:12.345678Z", None, OPAQUE)
