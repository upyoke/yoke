"""Resync repair: local-orphan epic-task body-budget regression.

Verifies that ``repair_local_orphan_epic_task`` routes the issue body
through the shared compact-mirror budget guard instead of passing the
raw oversized body to the typed ``github_rest.create_issue`` call. The
helper relies on the compact-mirror selector to keep the create payload
under the 62000-byte budget.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import backlog_github_body_budget as _budget
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


_OVER_BUDGET = "x" * (_budget.GITHUB_BODY_BUDGET_BYTES + 500)

# Minimal schema the repair helper reads. ``CAST(... AS INTEGER)`` on Postgres
# is satisfied by the identity-translated ``id`` column; the explicit
# columns mirror the production epic_tasks/items shape the readback queries.
_ITEMS_DDL = "CREATE TABLE items (id INTEGER PRIMARY KEY, github_issue TEXT)"
_EPIC_TASKS_DDL = (
    "CREATE TABLE epic_tasks ("
    " id INTEGER PRIMARY KEY,"
    " epic_id INTEGER,"
    " task_num INTEGER,"
    " title TEXT,"
    " status TEXT,"
    " body TEXT,"
    " github_issue TEXT"
    ")"
)
_EVENTS_DDL = (
    "CREATE TABLE events ("
    " id INTEGER PRIMARY KEY,"
    " event_name TEXT,"
    " item_id TEXT,"
    " created_at TEXT"
    ")"
)


def _apply_repair_schema() -> None:
    """Build the minimal schema on the backend-resolved test DB.

    The repair helper's body readback (``task_get_body`` via the backend-aware
    connect) and field update both resolve through the factory, so the schema
    + seed must live in the per-test DB the factory resolves — on Postgres the
    disposable per-test database init_test_db repoints the DSN at.
    """
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        conn.execute(_ITEMS_DDL)
        conn.execute(_EPIC_TASKS_DDL)
        conn.execute(_EVENTS_DDL)
        conn.commit()
    finally:
        conn.close()


def _seed_repair_rows(conn, *, item_id, github_issue, epic_id, task_num, title, body):
    conn.execute(
        "INSERT INTO items (id, github_issue) VALUES (%s, %s)",
        (item_id, github_issue),
    )
    conn.execute(
        "INSERT INTO epic_tasks (id, epic_id, task_num, title, status, body) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (task_num, int(epic_id), task_num, title, "planned", body),
    )


def _seed_repair_db(db_path: str, **rows) -> None:
    """Seed the backend-routed per-test DB."""
    conn = connect_test_db(db_path)
    try:
        _seed_repair_rows(conn, **rows)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def repair_db(tmp_path: Path):
    """Fresh DB with the minimal schema the repair helper needs (both engines)."""
    with init_test_db(tmp_path, apply_schema=_apply_repair_schema) as db_path:
        _seed_repair_db(
            str(db_path),
            item_id=9999, github_issue="#1",
            epic_id="9999", task_num=3,
            title="oversized orphan", body=_OVER_BUDGET,
        )
        yield str(db_path)


def test_repair_local_orphan_epic_task_sends_compact_mirror(monkeypatch, repair_db):
    from yoke_core.domain.github_rest import Issue
    from yoke_core.engines.resync_repair_epic_task_issue import (
        repair_local_orphan_epic_task,
    )

    captured: list[dict] = []

    def fake_create_issue(*, project, title, body, labels, **_kw):
        captured.append({
            "project": project, "title": title, "body": body, "labels": list(labels),
        })
        return Issue(number=5050, title=title, state="OPEN")

    monkeypatch.setattr(
        "yoke_core.engines.resync_repair_epic_task_issue.github_rest.create_issue",
        fake_create_issue,
    )

    update_calls: list[tuple[str, int, str, str]] = []

    def fake_update_field(conn, epic_id, task_num, field, value):
        update_calls.append((epic_id, task_num, field, value))

    ok = repair_local_orphan_epic_task(
        "9999/task-003",
        "yoke",
        repair_db,
        is_dry_run_fn=lambda: False,
        task_update_field_fn=fake_update_field,
    )

    assert ok is True
    assert len(captured) == 1
    create_payload = captured[0]
    # Body was routed through the compact-mirror selector — must be
    # under the 62000-byte budget even though the source body was over.
    assert _budget.body_exceeds_budget(create_payload["body"]) is False
    assert "YOK-9999 task 3" in create_payload["body"]
    assert "epic task-get-body 9999 3" in create_payload["body"]
    assert create_payload["labels"] == ["type:task", "status:planned"]
    # The task_update_field hook fires with the new issue number.
    assert update_calls == [("9999", 3, "github_issue", "#5050")]


def test_repair_local_orphan_epic_task_keeps_full_body_under_budget(
    monkeypatch, tmp_path,
):
    """Negative control: under-budget body ships verbatim."""
    from yoke_core.domain.github_rest import Issue
    from yoke_core.engines.resync_repair_epic_task_issue import (
        repair_local_orphan_epic_task,
    )

    captured: list[dict] = []

    def fake_create_issue(*, project, title, body, labels, **_kw):
        captured.append({"project": project, "title": title, "body": body, "labels": list(labels)})
        return Issue(number=42, title=title, state="OPEN")

    monkeypatch.setattr(
        "yoke_core.engines.resync_repair_epic_task_issue.github_rest.create_issue",
        fake_create_issue,
    )

    with init_test_db(tmp_path, apply_schema=_apply_repair_schema) as db_path:
        _seed_repair_db(
            str(db_path),
            item_id=123, github_issue="#7",
            epic_id="123", task_num=2,
            title="small task", body="small body",
        )

        ok = repair_local_orphan_epic_task(
            "123/task-002",
            "yoke",
            str(db_path),
            is_dry_run_fn=lambda: False,
            task_update_field_fn=lambda *a, **kw: None,
        )

    assert ok is True
    assert captured[0]["body"] == "small body"
