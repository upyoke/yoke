"""Pinned item-workflow progress for the Sessions roster."""

from __future__ import annotations

import json
import sqlite3

import pytest

from yoke_core.domain.session_item_stage_states import (
    item_stage_states,
    primary_item_stages_by_session,
)
from yoke_core.domain.workflow_runtime import builtin_workflow_runtime
from yoke_core.domain.work_claim_targets import make_item_target


WORKFLOWS = ("dash", "issue", "task", "epic", "blitz")


@pytest.mark.parametrize("workflow_id", WORKFLOWS)
def test_each_workflow_shape_marks_live_progress_in_declared_order(
    workflow_id: str,
) -> None:
    runtime = builtin_workflow_runtime(workflow_id)
    live_index = 1

    stages = item_stage_states(runtime, runtime.stage_ids[live_index])

    assert [stage["name"] for stage in stages] == [
        runtime.stage_label(stage_id) for stage_id in runtime.stage_ids
    ]
    assert [stage["state"] for stage in stages] == [
        "complete",
        "active",
        *(["pending"] * (len(runtime.stage_ids) - 2)),
    ]
    assert all(stage["failure"] is None for stage in stages)


@pytest.mark.parametrize("workflow_id", WORKFLOWS)
def test_landed_open_item_activates_closeout_without_a_red_segment(
    workflow_id: str,
) -> None:
    runtime = builtin_workflow_runtime(workflow_id)
    closeout = next(
        stage_id
        for stage_id in reversed(runtime.stage_ids)
        if stage_id not in runtime.terminal_stage_ids
    )

    stages = item_stage_states(
        runtime,
        runtime.stage_ids[0],
        landed_open=True,
    )

    assert stages[runtime.stage_index(closeout)]["state"] == "active"
    assert "failed" not in {stage["state"] for stage in stages}


def test_failure_attaches_to_its_named_stage() -> None:
    runtime = builtin_workflow_runtime("dash")
    failed_stage = "reviewing-implementation"

    stages = item_stage_states(
        runtime,
        failed_stage,
        failures={failed_stage: "QA failed"},
    )

    failed = stages[runtime.stage_index(failed_stage)]
    assert failed == {
        "name": "reviewing implementation",
        "state": "failed",
        "failure": "QA failed",
    }


def _connection() -> sqlite3.Connection:
    runtime = builtin_workflow_runtime("dash")
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            slug TEXT,
            name TEXT,
            public_item_prefix TEXT
        );
        CREATE TABLE workflow_versions (
            id INTEGER PRIMARY KEY,
            workflow_id TEXT,
            version INTEGER,
            definition_json TEXT,
            definition_digest TEXT
        );
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            project_id INTEGER,
            project_sequence INTEGER,
            status TEXT,
            blocked INTEGER,
            blocked_reason TEXT,
            merged_at TEXT,
            merge_queue_landed_at TEXT,
            workflow_id TEXT,
            workflow_version_id INTEGER
        );
        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            target_kind TEXT,
            scope TEXT,
            claimed_at TEXT,
            released_at TEXT
        );
        CREATE TABLE qa_requirements (
            id INTEGER PRIMARY KEY,
            item_id INTEGER,
            workflow_transition_id TEXT
        );
        CREATE TABLE qa_runs (
            id INTEGER PRIMARY KEY,
            qa_requirement_id INTEGER,
            verdict TEXT
        );
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            item_id TEXT,
            event_name TEXT,
            created_at TEXT
        );
        CREATE TABLE session_launches (
            launch_id TEXT PRIMARY KEY,
            project_id INTEGER,
            session_name TEXT,
            state TEXT,
            created_at TEXT
        );
        """
    )
    conn.execute("INSERT INTO projects VALUES (1,'yoke','Yoke','YOK')")
    conn.execute(
        "INSERT INTO workflow_versions VALUES (?,?,?,?,?)",
        (
            1,
            "dash",
            runtime.version,
            json.dumps(runtime.definition),
            runtime.definition_digest,
        ),
    )
    conn.execute(
        "INSERT INTO items VALUES (7,1,20,'implementing',0,NULL,NULL,NULL,'dash',1)"
    )
    conn.execute(
        "INSERT INTO work_claims VALUES (1,'s1','item',?,?,NULL)",
        (make_item_target(7).scope_json(), "2026-09-01T12:00:00Z"),
    )
    return conn


def _project(conn: sqlite3.Connection) -> list[dict[str, object]]:
    return primary_item_stages_by_session(conn, [{"session_id": "s1"}])["s1"]


@pytest.mark.parametrize(
    ("signal", "expected_stage", "expected_failure"),
    (
        ("qa", "reviewing implementation", "QA failed"),
        ("merge", "reviewing implementation", "CI checks failed"),
        ("launch", "implementing", "launch failed"),
        ("blocked", "implementing", "blocked: upstream unavailable"),
    ),
)
def test_projection_marks_only_real_failure_signals_red(
    signal: str,
    expected_stage: str,
    expected_failure: str,
) -> None:
    conn = _connection()
    if signal == "qa":
        conn.execute(
            "INSERT INTO qa_requirements VALUES (1,7,'reviewing-implementation')"
        )
        conn.execute("INSERT INTO qa_runs VALUES (1,1,'fail')")
    elif signal == "merge":
        conn.execute(
            "INSERT INTO events VALUES "
            "(1,7,'MergePullRequestCiFailed','2026-09-01T12:01:00Z')"
        )
    elif signal == "launch":
        conn.execute(
            "INSERT INTO session_launches VALUES "
            "('launch-1',1,'YOK-20: worker','failed','2026-09-01T12:01:00Z')"
        )
    else:
        conn.execute(
            "UPDATE items SET blocked=1,blocked_reason='upstream unavailable' "
            "WHERE id=7"
        )

    failures = [stage for stage in _project(conn) if stage["state"] == "failed"]

    assert failures == [
        {
            "name": expected_stage,
            "state": "failed",
            "failure": expected_failure,
        }
    ]


def test_projection_keeps_landed_open_item_blue_at_closeout() -> None:
    conn = _connection()
    conn.execute("UPDATE items SET merged_at='2026-09-01T12:02:00Z' WHERE id=7")

    stages = _project(conn)

    assert (
        next(stage for stage in stages if stage["name"] == "reviewing implementation")[
            "state"
        ]
        == "active"
    )
    assert "failed" not in {stage["state"] for stage in stages}


def test_projection_uses_focus_then_the_newest_held_item() -> None:
    conn = _connection()
    conn.execute(
        "INSERT INTO items VALUES "
        "(8,1,21,'reviewing-implementation',0,NULL,NULL,NULL,'dash',1)"
    )
    conn.execute(
        "INSERT INTO work_claims VALUES (2,'s1','item',?,?,NULL)",
        (make_item_target(8).scope_json(), "2026-09-01T12:01:00Z"),
    )

    newest = _project(conn)
    focused = primary_item_stages_by_session(
        conn,
        [{"session_id": "s1", "current_item": "YOK-20"}],
    )["s1"]

    assert newest[2]["state"] == "active"
    assert focused[1]["state"] == "active"


def test_projection_clears_a_swept_error_once_a_continuation_run_lands() -> None:
    """A settled walk's error verdict stops painting the strip red.

    Terminal settlement stamps an unreviewed mission capture with an error
    verdict, which is a truthful record of that execution and not a verdict
    on the walk. A continuation records its own run for the same
    requirement, and the projection reads the latest run, so the newer row
    is what the strip shows.
    """
    conn = _connection()
    conn.execute("INSERT INTO qa_requirements VALUES (1,7,'reviewing-implementation')")
    conn.execute("INSERT INTO qa_runs VALUES (1,1,'error')")

    swept = [stage for stage in _project(conn) if stage["state"] == "failed"]
    assert swept == [
        {
            "name": "reviewing implementation",
            "state": "failed",
            "failure": "QA failed",
        }
    ]

    conn.execute("INSERT INTO qa_runs VALUES (2,1,NULL)")

    assert "failed" not in {stage["state"] for stage in _project(conn)}


def test_projection_omits_a_session_without_an_item() -> None:
    conn = _connection()

    assert (
        primary_item_stages_by_session(conn, [{"session_id": "steering-session"}]) == {}
    )
