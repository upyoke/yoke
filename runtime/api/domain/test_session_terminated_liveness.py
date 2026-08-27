"""A killed session is ended, and every kill mechanic still holds.

Liveness folds a kill into ``ended``; ``ended_cause`` carries the kill. The
refusals below all read ``terminated_at``, so the presentation fold must not
move any of them.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from runtime.api.domain.test_session_message_support import (
    NOW,
    message_connection,
    selector,
)
from runtime.api.test_sessions import _register
from yoke_contracts.session_control.liveness import LIVENESS_ENDED, LIVENESS_STATES
from yoke_core.domain.session_message_delivery import lease_for_hook
from yoke_core.domain.session_message_liveness import applied_liveness
from yoke_core.domain.session_message_routing import messageability, session_liveness
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.sessions import SessionError, end_session
from yoke_core.domain.sessions_ended_recovery import (
    session_ended_message,
    session_registration_state,
)


pytest_plugins = ("runtime.api.test_sessions",)


def test_ordinary_ended_session_still_reactivates(conn) -> None:
    _register(conn, session_id="ordinary")
    end_session(conn, "ordinary")

    reactivated = _register(conn, session_id="ordinary")

    assert reactivated["ended_at"] is None
    assert reactivated["terminated_at"] is None
    found, actor_id, ended = session_registration_state(conn, "ordinary")
    # Registration binds the universe's operating actor, so the reactivated
    # row reports one; `ended` False is what keeps a further revival off.
    assert (found, ended) == (True, False)
    assert actor_id is not None


def test_terminated_session_never_requests_registration_or_reactivation(conn) -> None:
    _register(conn, session_id="permanent")
    conn.execute(
        "UPDATE harness_sessions SET ended_at=%s,terminated_at=%s,"
        "termination_reason='operator stopped worker' "
        "WHERE session_id='permanent'",
        ("2026-08-26T12:00:00Z", "2026-08-26T12:00:00Z"),
    )
    conn.commit()

    found, actor_id, ended = session_registration_state(conn, "permanent")
    assert (found, ended) == (True, False)
    assert actor_id is not None
    assert session_ended_message(conn, "permanent") == (
        "Session 'permanent' has been permanently terminated."
    )
    with pytest.raises(SessionError) as exc_info:
        _register(conn, session_id="permanent")
    assert exc_info.value.code == "SESSION_TERMINATED"
    stored = conn.execute(
        "SELECT ended_at,terminated_at FROM harness_sessions "
        "WHERE session_id='permanent'"
    ).fetchone()
    assert stored["ended_at"] and stored["terminated_at"]


def test_killed_session_is_non_messageable_and_non_wakeable() -> None:
    conn = message_connection()
    message_id = send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=["s1"]),
        body="This must never wake a terminated session.",
        now=NOW,
    )["message_id"]
    conn.execute(
        "UPDATE harness_sessions SET ended_at=?,terminated_at=? WHERE session_id='s1'",
        ("2026-08-26T12:00:00Z", "2026-08-26T12:00:00Z"),
    )
    conn.execute(
        "UPDATE session_message_recipients SET wake_after=? WHERE message_id=?",
        ("2026-08-26T12:00:00Z", message_id),
    )
    conn.commit()

    row = dict(
        conn.execute("SELECT * FROM harness_sessions WHERE session_id='s1'").fetchone()
    )
    liveness = session_liveness(row, now=NOW + timedelta(days=1))
    assert liveness == LIVENESS_ENDED
    assert messageability(row, liveness=liveness) == {
        "messageable": False,
        "hook_injection": False,
        "wake_interface": "none",
        "reason": "session_terminated",
    }
    assert (
        lease_for_hook(
            conn,
            session_id="s1",
            hook_event="PreToolUse",
            limit=10,
        )
        is None
    )
    assert wake_eligible_recipients(conn, now=NOW + timedelta(days=1)) == []


def test_exact_session_selectors_resolve_against_every_state() -> None:
    states = applied_liveness(selector(session_ids=["s1"]))
    assert states == LIVENESS_STATES


def test_liveness_has_no_terminated_peer_value() -> None:
    assert "terminated" not in LIVENESS_STATES
