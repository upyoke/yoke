"""The session card strip reads the live claim, not the item status alone."""

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


def test_claimed_dash_at_idea_paints_idea_done_and_implementing_active() -> None:
    runtime = builtin_workflow_runtime("dash")

    stages = item_stage_states(runtime, "idea", holder_mode="dash")

    assert active_stage_id(runtime, "idea", holder_mode="dash") == "implementing"
    assert _states(stages) == ["complete", "active", "pending", "pending"]


@pytest.mark.parametrize("holder_mode", (None, "wait", "idea"))
def test_dash_at_idea_without_a_working_claim_keeps_idea_active(
    holder_mode: str | None,
) -> None:
    """Unclaimed, or claimed by a session not yet working the Dash skill."""
    runtime = builtin_workflow_runtime("dash")

    stages = item_stage_states(runtime, "idea", holder_mode=holder_mode)

    assert _states(stages) == ["active", "pending", "pending", "pending"]


def test_issue_mid_implementation_keeps_the_status_derived_stage() -> None:
    runtime = builtin_workflow_runtime("issue")

    stages = item_stage_states(runtime, "implementing", holder_mode="busy")

    assert stages[runtime.stage_index("implementing")]["state"] == "active"
    assert _states(stages)[: runtime.stage_index("implementing")] == [
        "complete"
    ] * runtime.stage_index("implementing")


def test_handoff_stage_completes_once_the_bound_skill_is_working() -> None:
    """A binding's first stage is the previous skill's handoff."""
    runtime = builtin_workflow_runtime("issue")

    assert active_stage_id(runtime, "idea", holder_mode="refine") == "refining-idea"
    # Polish's handoff stage is reviewed-implementation; its working stage
    # follows it.
    assert (
        active_stage_id(runtime, "reviewed-implementation", holder_mode="polish")
        == "polishing-implementation"
    )
    # A skill working past its handoff keeps the status-derived stage.
    assert active_stage_id(runtime, "refining-idea", holder_mode="refine") == (
        "refining-idea"
    )


def test_single_stage_binding_has_no_working_stage_to_advance_to() -> None:
    runtime = builtin_workflow_runtime("task")

    assert active_stage_id(runtime, "implementing", holder_mode="dash") == (
        "implementing"
    )


def test_landed_open_item_outranks_the_live_claim() -> None:
    runtime = builtin_workflow_runtime("dash")

    assert (
        active_stage_id(runtime, "idea", landed_open=True, holder_mode="dash")
        == "reviewing-implementation"
    )


def _connection(*, status: str, holder_mode: str | None) -> sqlite3.Connection:
    runtime = builtin_workflow_runtime("dash")
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
        """
    )
    conn.execute("INSERT INTO projects VALUES (1,'yoke','Yoke','YOK')")
    conn.execute(
        "INSERT INTO workflow_versions VALUES (1,'dash',?,?,?)",
        (runtime.version, json.dumps(runtime.definition), runtime.definition_digest),
    )
    conn.execute(
        "INSERT INTO items VALUES (7,1,20,?,0,NULL,NULL,NULL,'dash',1)",
        (status,),
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


def test_projection_reads_the_claim_holder_mode() -> None:
    working = _connection(status="idea", holder_mode="dash")
    waiting = _connection(status="idea", holder_mode="wait")

    assert _states(
        primary_item_stages_by_session(working, [{"session_id": "s1"}])["s1"]
    ) == [
        "complete",
        "active",
        "pending",
        "pending",
    ]
    assert _states(
        primary_item_stages_by_session(waiting, [{"session_id": "s1"}])["s1"]
    ) == [
        "active",
        "pending",
        "pending",
        "pending",
    ]


def test_projection_reads_the_holder_mode_for_a_lane_session() -> None:
    """A lane row on another session's claimed Dash sees the same strip."""
    conn = _connection(status="idea", holder_mode="dash")

    stages = primary_item_stages_by_session(
        conn,
        [
            {
                "session_id": "lane",
                "work_role": "implementation",
                "current_item": "YOK-20",
            }
        ],
    )

    assert _states(stages["lane"]) == ["complete", "active", "pending", "pending"]


def test_projection_pins_a_launch_failure_to_the_working_stage() -> None:
    conn = _connection(status="idea", holder_mode="dash")
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

    stages = primary_item_stages_by_session(conn, [{"session_id": "s1"}])["s1"]

    assert stages[1] == {
        "name": "implementing",
        "state": "failed",
        "failure": "launch failed",
    }
    assert stages[0]["state"] == "complete"
