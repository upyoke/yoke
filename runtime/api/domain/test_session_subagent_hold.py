"""A receipt held behind a running subagent is reported as exactly that.

Observed: a parent that started a background agent and ended its turn held
two steering messages for over an hour while the fleet report said a turn,
then an attempt, was in flight. Every hook in that window was the child's
and declined the parent's inbox with ``probe_subagent_exit``.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from yoke_contracts.timestamps import format_instant, parse_instant

import pytest

from runtime.api.domain.test_session_subagent_activity import (
    CHILD_DONE,
    CHILD_START,
    PARENT_STOP,
    parent_then_background_child,
    seed_parent,
)
from runtime.api.steering_fleet_test_helpers import (
    ANSWERER,
    ASKER,
    PROJECT_ID,
    seed_message,
    seed_session,
)
from yoke_core.domain.fleet_delta_alarms import DeltaState, starved_envelope_alarms
from yoke_core.domain.fleet_delta_snapshot import EnvelopeRow, FleetSnapshot, SessionRow
from yoke_core.domain.session_message_delivery_probe import (
    PROBE_SUBAGENT_EXIT,
    record_undelivered_receipts,
)
from yoke_core.domain.steering_fleet_report_delivery_states import (
    HELD_BEHIND_SUBAGENT,
)
from yoke_core.domain.steering_fleet_report_render_undelivered import (
    undelivered_line,
)
from yoke_core.domain.steering_fleet_report_undelivered import undelivered_messages

@pytest.fixture
def parent(test_db):
    return seed_parent(test_db)


SENT = PARENT_STOP + timedelta(seconds=10)
NOW = CHILD_DONE + timedelta(minutes=40)


def _decline(conn, at: datetime) -> None:
    record_undelivered_receipts(
        conn,
        session_id=ANSWERER,
        hook_event="PostToolUse",
        reason=PROBE_SUBAGENT_EXIT,
        now=at,
    )


def _held(conn) -> list:
    return list(undelivered_messages(conn, project_id=PROJECT_ID, now=format_instant(NOW)))


def _send(conn) -> None:
    seed_session(conn, ASKER)
    seed_message(conn, "msg-held", sender=ASKER, to=ANSWERER, at=SENT)
    conn.commit()


def test_subagent_declines_classify_as_held_with_both_clocks(parent):
    _send(parent)
    parent_then_background_child(parent)
    parent.commit()
    _decline(parent, CHILD_START)
    _decline(parent, CHILD_DONE)

    rows = _held(parent)

    assert [row.delivery_state for row in rows] == [HELD_BEHIND_SUBAGENT]
    held = rows[0]
    assert held.parent_idle_since == PARENT_STOP
    assert held.held_subagent_type == "Explore"
    assert held.held_subagent_since == CHILD_START
    assert held.held_declined_at == CHILD_DONE
    line = undelivered_line(held)
    assert f"parent idle since {format_instant(PARENT_STOP)}" in line
    assert f"subagent Explore running since {format_instant(CHILD_START)}" in line
    assert "delivers on the parent's next hook" in line
    assert "in flight" not in line


def test_an_open_child_call_alone_holds_the_receipt(parent):
    """No decline recorded yet: the open call is the child's, not the parent's."""
    _send(parent)
    parent_then_background_child(parent)
    parent.commit()

    assert [row.delivery_state for row in _held(parent)] == [HELD_BEHIND_SUBAGENT]


def test_repeated_subagent_declines_advance_the_last_decline_time(parent):
    _send(parent)
    first, later = CHILD_START, CHILD_START + timedelta(minutes=30)
    _decline(parent, first)
    _decline(parent, later)

    rows = parent.execute(
        "SELECT started_at, completed_at, result_code FROM session_message_attempts "
        "WHERE message_id = %s",
        ("msg-held",),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["result_code"] == PROBE_SUBAGENT_EXIT
    assert parse_instant(rows[0]["started_at"]) == first
    assert parse_instant(rows[0]["completed_at"]) == later

    _decline(parent, first)
    again = parent.execute(
        "SELECT completed_at FROM session_message_attempts WHERE message_id = %s",
        ("msg-held",),
    ).fetchone()
    assert parse_instant(again["completed_at"]) == later


def test_the_starved_envelope_alarm_fires_while_the_subagent_works(parent):
    _send(parent)
    parent_then_background_child(parent)
    parent.commit()
    recorded = parent.execute(
        "SELECT last_tool_call_at FROM harness_sessions WHERE session_id = %s",
        (ANSWERER,),
    ).fetchone()["last_tool_call_at"]
    envelope = EnvelopeRow(
        message_id="msg-held",
        recipient_session_id=ANSWERER,
        sender_session_id=ASKER,
        state="pending",
        injection_count=0,
        created_at=SENT,
    )
    snapshot = FleetSnapshot(
        taken_at=NOW,
        self_session_id="steerer",
        sessions={
            ANSWERER: SessionRow(
                session_id=ANSWERER,
                executor_surface="claude-cli",
                mode="dash",
                parked=False,
                ended=False,
                terminated=False,
                activity_at=CHILD_DONE,
                claimed_items=(),
                last_tool_call_at=parse_instant(recorded),
            )
        },
        items={},
        envelopes={envelope.key: envelope},
    )

    fired = starved_envelope_alarms(snapshot, DeltaState())

    assert fired and "ALARM starved-envelope" in fired[0]
