# ruff: noqa: F811
"""What a proven-dead process report ends, and what it must leave standing.

The report is machine evidence about a process, never a verdict about the
session's authority. These cases pin both halves: a launch-named exit ends a
settled session on the poll that observed it, and a session that still holds
something, declared a wait, or is owed an answer keeps its row.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.sessions_api_stale_test_helpers import _ago_minutes
from runtime.api.domain.test_session_process_liveness_report import (
    ANCHOR_EVIDENCE,
    EVIDENCE,
    MACHINE,
    _apply,
    _session_row,
)
from runtime.api.test_sessions import _insert_claimable_items, _register
from yoke_core.domain.session_mode import set_session_mode
from yoke_core.domain.session_native_process_observation import (
    AWAITING_SEAT_REPLY_STATUS,
    PARKED_STATUS,
    current_native_process_observation,
)


@pytest.fixture(autouse=True)
def _claimable_items(conn):
    _insert_claimable_items(conn, 9301)


@pytest.fixture
def conn(test_db):
    return test_db


def _live(conn, session_id: str = "sess-fresh-ghost") -> str:
    """A registered session whose heartbeat is seconds old, not minutes."""
    _register(conn, session_id=session_id, machine_id=MACHINE)
    conn.execute(
        "UPDATE harness_sessions SET machine_id=%s WHERE session_id=%s",
        (MACHINE, session_id),
    )
    conn.commit()
    return session_id


def _inbound(conn, session_id: str, message_id: str = "msg-inbound") -> None:
    """One envelope waiting in this session's inbox."""
    sent = _ago_minutes(1)
    expires = _ago_minutes(-60)
    conn.execute(
        "INSERT INTO session_messages (message_id, sender_actor_id, body, "
        "body_sha256, selector_snapshot, created_at, expires_at) "
        "VALUES (%s, 1, 'landed: the branch is merged', 'sha', '{}', %s, %s)",
        (message_id, sent, expires),
    )
    conn.execute(
        "INSERT INTO session_message_recipients (message_id, session_id, "
        "project_id, resolution_evidence, routing_snapshot, state, created_at, "
        "wake_after) VALUES (%s, %s, 1, '{}', '{}', 'pending', %s, %s)",
        (message_id, session_id, sent, sent),
    )
    conn.commit()


def _told_the_seat(conn, session_id: str, body: str, message_id: str) -> None:
    """One role-addressed message this session sent to the steering seat."""
    sent = _ago_minutes(1)
    expires = _ago_minutes(-60)
    conn.execute(
        "INSERT INTO session_messages (message_id, sender_actor_id, "
        "sender_session_id, body, body_sha256, selector_snapshot, created_at, "
        "expires_at) VALUES (%s, 1, %s, %s, 'sha', '{}', %s, %s)",
        (message_id, session_id, body, sent, expires),
    )
    conn.execute(
        "INSERT INTO actor_message_recipients (message_id, recipient_kind, "
        "state, steering_scope, project_id, created_at) "
        "VALUES (%s, 'steering', 'awaiting_seat', %s, 1, %s)",
        (message_id, json.dumps({"project_id": 1}), sent),
    )
    conn.commit()


def _recipient_states(conn, session_id: str) -> list[str]:
    return [
        str(dict(row)["state"])
        for row in conn.execute(
            "SELECT state FROM session_message_recipients WHERE session_id=%s",
            (session_id,),
        ).fetchall()
    ]


def test_a_launch_named_exit_ends_the_session_without_waiting_for_the_ttl(conn):
    """The machine started this native, so its death needs no TTL to confirm."""
    session_id = _live(conn)

    assert _apply(conn, session_id)["ended"] == [session_id]
    assert _session_row(conn, session_id)["ended_at"]


def test_an_anchor_only_exit_still_waits_for_the_staleness_ttl(conn):
    """No launch behind the record, so the control plane keeps its ambiguity."""
    session_id = _live(conn, "sess-anchor-ghost")

    assert _apply(conn, session_id, evidence=ANCHOR_EVIDENCE)["skipped"] == [
        {"session_id": session_id, "status": "liveness_active"}
    ]
    assert _session_row(conn, session_id)["ended_at"] is None


def test_ending_a_dead_recipient_cancels_the_envelopes_nobody_will_read(conn):
    session_id = _live(conn)
    _inbound(conn, session_id)
    assert _recipient_states(conn, session_id) == ["pending"]

    assert _apply(conn, session_id)["ended"] == [session_id]
    assert _recipient_states(conn, session_id) == ["cancelled"]


def test_a_parked_session_keeps_its_row_and_carries_the_observation(conn):
    session_id = _live(conn, "sess-parked-ghost")
    set_session_mode(conn, session_id, "parked", "waiting on the seat")
    conn.commit()

    assert _apply(conn, session_id)["skipped"] == [
        {"session_id": session_id, "status": PARKED_STATUS}
    ]
    row = _session_row(conn, session_id)
    assert row["ended_at"] is None
    assert current_native_process_observation(row) == {
        "state": "gone",
        "observed_at": row["native_process_gone_at"],
        "evidence": EVIDENCE,
    }


def test_a_session_awaiting_the_seats_answer_keeps_its_row(conn):
    session_id = _live(conn, "sess-asking-ghost")
    _told_the_seat(
        conn,
        session_id,
        "Should I widen the claim or wait for the holder?",
        "msg-open-question",
    )

    assert _apply(conn, session_id)["skipped"] == [
        {"session_id": session_id, "status": AWAITING_SEAT_REPLY_STATUS}
    ]
    assert _session_row(conn, session_id)["ended_at"] is None


def test_a_terminal_report_to_the_seat_is_not_a_wait(conn):
    """A DONE report asks for nothing, so it must not keep the row alive."""
    session_id = _live(conn, "sess-reporting-ghost")
    _told_the_seat(
        conn,
        session_id,
        "DONE YOK-1 merged and closed out.",
        "msg-terminal-report",
    )

    assert _apply(conn, session_id)["ended"] == [session_id]
