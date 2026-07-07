"""Tests for ``qa_events.resolve_requirement_event_target``.

Covers AC-9 (a) from the parent task spec: item-target, epic-task-target,
and deployment-run-target rows.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import qa_events
from yoke_core.domain._qa_events_test_helpers import (
    fetch_row,
    insert_deployment_requirement,
    insert_epic_requirement,
    insert_item_requirement,
    make_conn,
)


@pytest.fixture
def conn():
    c = make_conn()
    try:
        yield c
    finally:
        c.close()


def test_resolve_target_item(conn):
    insert_item_requirement(conn, req_id=1, item_id=42)
    row = fetch_row(conn, 1)
    item_ref, task_num_ref = qa_events.resolve_requirement_event_target(row)
    assert item_ref == "42"
    assert task_num_ref is None


def test_resolve_target_epic_task(conn):
    insert_epic_requirement(conn, req_id=2, epic_id=100, task_num=3)
    row = fetch_row(conn, 2)
    item_ref, task_num_ref = qa_events.resolve_requirement_event_target(row)
    assert item_ref == "100"
    assert task_num_ref == 3


def test_resolve_target_epic_no_task_num(conn):
    """Epic-only target with no task_num returns None for task_num_ref."""
    conn.execute(
        "INSERT INTO qa_requirements (id, epic_id, qa_kind, qa_phase, created_at) "
        "VALUES (%s, %s, %s, %s, %s)",
        (10, 200, "implementation_review", "verification", "2026-01-01T00:00:00Z"),
    )
    conn.commit()
    row = fetch_row(conn, 10)
    item_ref, task_num_ref = qa_events.resolve_requirement_event_target(row)
    assert item_ref == "200"
    assert task_num_ref is None


def test_resolve_target_deployment_run(conn):
    insert_deployment_requirement(conn, req_id=3, run_id="run-abc-001")
    row = fetch_row(conn, 3)
    item_ref, task_num_ref = qa_events.resolve_requirement_event_target(row)
    assert item_ref == "run-abc-001"
    assert task_num_ref is None


def test_resolve_target_none_row():
    item_ref, task_num_ref = qa_events.resolve_requirement_event_target(None)
    assert item_ref is None
    assert task_num_ref is None


def test_resolve_target_dict_row():
    """Dict-like rows work the same as sqlite3.Row (column-name indexing)."""
    item_ref, task_num_ref = qa_events.resolve_requirement_event_target(
        {"item_id": 7, "epic_id": None, "task_num": None, "deployment_run_id": None}
    )
    assert item_ref == "7"
    assert task_num_ref is None
