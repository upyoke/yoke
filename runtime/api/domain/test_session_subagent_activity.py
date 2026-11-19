"""A subagent's tool calls are recorded as child activity, never the parent's.

A subagent shares its parent's session id. Its calls used to stamp the
parent's ``last_tool_call_at`` and turn posture, so a parent that started a
background agent and ended its turn read as a turn in flight while every
hook in that window was the child's and declined to read the parent's inbox.
"""

from __future__ import annotations

from datetime import timedelta

from yoke_contracts.timestamps import format_instant, parse_instant

import pytest

from runtime.api.steering_fleet_test_helpers import ANSWERER, BEFORE_THAT, seed_session
from yoke_core.domain.session_activity_state import apply_envelope_state
from yoke_core.domain.session_message_starvation import starved_hook_route
from yoke_core.domain.session_reclaim_progress import tool_activity_stamp
from yoke_core.domain.session_turn_posture import stamp_turn_posture

PARENT_CALL = parse_instant("2026-08-26T10:00:00Z")
PARENT_STOP = PARENT_CALL + timedelta(seconds=30)
CHILD_START = PARENT_STOP + timedelta(minutes=1)
CHILD_DONE = CHILD_START + timedelta(seconds=20)


def call(name: str, tool_use_id: str, at, *, agent: str | None = None) -> dict:
    envelope = {
        "event_name": name,
        "session_id": ANSWERER,
        "tool_use_id": tool_use_id,
        "tool_name": "Bash",
        "event_time": format_instant(at),
        "event_outcome": "completed",
    }
    if agent:
        envelope["agent"] = agent
    return envelope


def parent_then_background_child(conn, *, child_open: bool = True) -> None:
    """A parent call, a parent Stop, then a background subagent working."""
    apply_envelope_state(conn, call("HarnessToolCallStarted", "p-1", PARENT_CALL))
    apply_envelope_state(conn, call("HarnessToolCallCompleted", "p-1", PARENT_CALL))
    stamp_turn_posture(
        conn, session_id=ANSWERER, posture="waiting", observed_at=PARENT_STOP
    )
    apply_envelope_state(
        conn, call("HarnessToolCallStarted", "c-1", CHILD_START, agent="Explore")
    )
    apply_envelope_state(
        conn, call("HarnessToolCallCompleted", "c-1", CHILD_DONE, agent="Explore")
    )
    if child_open:
        apply_envelope_state(
            conn,
            call(
                "HarnessToolCallStarted",
                "c-2",
                CHILD_DONE + timedelta(seconds=5),
                agent="Explore",
            ),
        )


@pytest.fixture
def parent(test_db):
    seed_session(
        test_db,
        ANSWERER,
        last_tool_call_at=BEFORE_THAT,
        executor="claude-code",
        executor_surface="claude-cli",
    )
    test_db.commit()
    return test_db


def _session(conn) -> dict:
    return dict(
        conn.execute(
            "SELECT last_tool_call_at, last_child_tool_call_at, turn_posture, "
            "turn_posture_at, tool_call_count FROM harness_sessions "
            "WHERE session_id = %s",
            (ANSWERER,),
        ).fetchone()
    )


def test_subagent_calls_leave_the_parents_clock_and_posture_alone(parent):
    parent_then_background_child(parent)

    row = _session(parent)
    assert parse_instant(row["last_tool_call_at"]) == PARENT_CALL
    assert row["turn_posture"] == "waiting"
    assert parse_instant(row["turn_posture_at"]) == PARENT_STOP
    assert parse_instant(row["last_child_tool_call_at"]) == CHILD_DONE
    assert row["tool_call_count"] == 2
    assert tool_activity_stamp(row) == CHILD_DONE


def test_parent_calls_still_move_the_parents_clock_and_posture(parent):
    parent_then_background_child(parent)
    later = CHILD_DONE + timedelta(minutes=5)

    apply_envelope_state(parent, call("HarnessToolCallStarted", "p-2", later))
    apply_envelope_state(parent, call("HarnessToolCallCompleted", "p-2", later))

    row = _session(parent)
    assert parse_instant(row["last_tool_call_at"]) == later
    assert row["turn_posture"] == "running"
    assert parse_instant(row["turn_posture_at"]) == later


def test_child_rows_are_marked_with_their_agent(parent):
    parent_then_background_child(parent)

    rows = parent.execute(
        "SELECT tool_use_id, agent_type, completed_at FROM session_tool_calls "
        "WHERE session_id = %s ORDER BY id",
        (ANSWERER,),
    ).fetchall()
    assert [(row["tool_use_id"], row["agent_type"]) for row in rows] == [
        ("p-1", None),
        ("c-1", "Explore"),
        ("c-2", "Explore"),
    ]
    assert rows[2]["completed_at"] is None


def test_the_starvation_clock_runs_on_the_parents_own_silence(parent):
    """A busy subagent no longer hides a parent that runs no hook of its own."""
    parent_then_background_child(parent)
    sent = PARENT_STOP + timedelta(seconds=10)
    row = {
        **_session(parent),
        "state": "pending",
        "injection_count": 0,
        "message_created_at": sent,
        "executor_surface": "claude-cli",
        "launch_origin": "yoke",
    }

    assert starved_hook_route(
        row, grace_seconds=300, now=CHILD_DONE + timedelta(minutes=10)
    )
