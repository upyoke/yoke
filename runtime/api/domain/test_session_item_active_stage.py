"""The session card strip paints the stage the item's status names."""

from __future__ import annotations

import json
import sqlite3

import pytest

from yoke_core.domain.session_item_stage_states import (
    active_stage_id,
    item_stage_states,
    primary_item_stages_by_session,
)
from yoke_core.domain.workflow_runtime import builtin_workflow_runtime
from yoke_core.domain.work_claim_targets import make_item_target


def _states(stages: list[dict[str, object]]) -> list[object]:
    return [stage["state"] for stage in stages]


def _status_states(runtime, status: str) -> list[object]:
    index = runtime.stage_index(status)
    return [
        "complete" if position < index else "active" if position == index else "pending"
        for position in range(len(runtime.stage_ids))
    ]


@pytest.mark.parametrize(
    ("workflow_id", "status"),
    (
        ("dash", "idea"),
        ("issue", "idea"),
        ("issue", "implementing"),
        ("issue", "reviewed-implementation"),
        ("task", "implementing"),
    ),
)
def test_strip_paints_the_status_stage_active(workflow_id: str, status: str) -> None:
    runtime = builtin_workflow_runtime(workflow_id)

    assert active_stage_id(runtime, status) == status
    assert _states(item_stage_states(runtime, status)) == _status_states(
        runtime, status
    )


def test_landed_open_item_paints_the_verification_close() -> None:
    runtime = builtin_workflow_runtime("dash")

    assert (
        active_stage_id(runtime, "idea", landed_open=True)
        == "reviewing-implementation"
    )


def _connection(
    *, status: str, holder_mode: str | None, workflow_id: str = "dash"
) -> sqlite3.Connection:
    runtime = builtin_workflow_runtime(workflow_id)
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY, slug TEXT, name TEXT, public_item_prefix TEXT
        );
        CREATE TABLE workflow_versions (
            id INTEGER PRIMARY KEY, workflow_id TEXT, version INTEGER,
            definition_json TEXT, definition_digest TEXT
        );
        CREATE TABLE items (
            id INTEGER PRIMARY KEY, project_id INTEGER, project_sequence INTEGER,
            status TEXT, blocked INTEGER, blocked_reason TEXT, merged_at TEXT,
            merge_queue_landed_at TEXT, workflow_id TEXT,
            workflow_version_id INTEGER
        );
        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY, session_id TEXT, target_kind TEXT,
            scope TEXT, claimed_at TEXT, released_at TEXT
        );
        CREATE TABLE harness_sessions (session_id TEXT PRIMARY KEY, mode TEXT);
        CREATE TABLE item_status_transitions (
            id INTEGER PRIMARY KEY, item_id INTEGER, task_num INTEGER,
            to_status TEXT, created_at TEXT
        );
        """
    )
    conn.execute("INSERT INTO projects VALUES (1,'yoke','Yoke','YOK')")
    conn.execute(
        "INSERT INTO workflow_versions VALUES (1,?,?,?,?)",
        (
            workflow_id,
            runtime.version,
            json.dumps(runtime.definition),
            runtime.definition_digest,
        ),
    )
    conn.execute(
        "INSERT INTO items VALUES (7,1,20,?,0,NULL,NULL,NULL,?,1)",
        (status, workflow_id),
    )
    conn.execute("INSERT INTO harness_sessions VALUES ('s1','wait')")
    if holder_mode is not None:
        conn.execute(
            "INSERT INTO work_claims VALUES (1,'s1','item',?,?,NULL)",
            (make_item_target(7).scope_json(), "2026-09-01T12:00:00Z"),
        )
        conn.execute(
            "UPDATE harness_sessions SET mode=? WHERE session_id='s1'", (holder_mode,)
        )
    return conn


@pytest.mark.parametrize("holder_mode", ("wait", "parked", "dash"))
def test_held_item_strip_equals_its_status_stage(holder_mode: str) -> None:
    """A holder's stored mode, even an old skill mode, never moves the strip."""
    runtime = builtin_workflow_runtime("dash")
    conn = _connection(status="idea", holder_mode=holder_mode)

    stages = primary_item_stages_by_session(conn, [{"session_id": "s1"}])["s1"]

    assert _states(stages) == _status_states(runtime, "idea")


@pytest.mark.parametrize("landing_field", ("merged_at", "merge_queue_landed_at"))
def test_held_session_card_trusts_post_merge_return_to_implementing(
    landing_field: str,
) -> None:
    conn = _connection(status="implementing", holder_mode="wait")
    conn.execute(
        f"UPDATE items SET {landing_field}=? WHERE id=7",
        ("2026-09-01T12:02:00Z",),
    )
    conn.execute(
        "INSERT INTO item_status_transitions VALUES (1,7,NULL,?,?)",
        ("implementing", "2026-09-01T13:00:00Z"),
    )

    stages = primary_item_stages_by_session(conn, [{"session_id": "s1"}])["s1"]

    assert _states(stages) == ["complete", "active", "pending", "pending", "pending"]
    assert stages[1] == {"name": "implementing", "state": "active", "failure": None}


@pytest.mark.parametrize("history", ("before_merge", "task", "different_status"))
def test_held_session_card_keeps_closeout_for_stale_merge_status(
    history: str,
) -> None:
    conn = _connection(status="implementing", holder_mode="wait")
    conn.execute("UPDATE items SET merged_at='2026-09-01T12:02:00Z' WHERE id=7")
    if history != "before_merge":
        conn.execute(
            "INSERT INTO item_status_transitions VALUES (1,7,?,?,?)",
            (
                1 if history == "task" else None,
                "implementing" if history == "task" else "reviewing-implementation",
                "2026-09-01T13:00:00Z",
            ),
        )
    else:
        conn.execute(
            "INSERT INTO item_status_transitions VALUES (1,7,NULL,?,?)",
            ("implementing", "2026-09-01T12:01:00Z"),
        )

    stages = primary_item_stages_by_session(conn, [{"session_id": "s1"}])["s1"]

    assert stages[2]["state"] == "active"
    assert stages[1]["state"] == "complete"


def test_lane_session_on_a_claimed_item_sees_the_status_stage() -> None:
    """A lane row on another session's claimed Dash sees the same strip."""
    conn = _connection(status="implementing", holder_mode="wait")

    stages = primary_item_stages_by_session(
        conn,
        [{"session_id": "lane", "work_role": "implementation", "current_item": "YOK-20"}],
    )

    assert _states(stages["lane"]) == [
        "complete",
        "active",
        "pending",
        "pending",
        "pending",
    ]


def _failed_launch(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE session_launches (
            launch_id TEXT PRIMARY KEY, project_id INTEGER, session_name TEXT,
            state TEXT, created_at TEXT
        );
        INSERT INTO session_launches VALUES
            ('launch-1',1,'YOK-20: worker','failed','2026-09-01T12:01:00Z');
        """
    )


def test_projection_ignores_launch_failure_once_item_has_live_holder() -> None:
    conn = _connection(status="idea", holder_mode="wait")
    _failed_launch(conn)

    stages = primary_item_stages_by_session(conn, [{"session_id": "s1"}])["s1"]

    assert stages[0] == {"name": "idea", "state": "active", "failure": None}


def test_projection_keeps_launch_failure_without_live_holder() -> None:
    conn = _connection(status="idea", holder_mode=None)
    _failed_launch(conn)

    stages = primary_item_stages_by_session(
        conn,
        [{"session_id": "lane", "work_role": "implementation", "current_item": "YOK-20"}],
    )["lane"]

    assert stages[0] == {"name": "idea", "state": "failed", "failure": "launch failed"}
