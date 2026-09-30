"""A recipient whose native the machine watched exit is resumed at once."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_starvation import STARVED_HOOK_ROUTE
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.session_relay_versions import wake_operation
from yoke_core.domain.session_wake_process_absence import NATIVE_PROCESS_GONE
from yoke_core.domain.session_native_process_observation import (
    current_native_process_observation,
)
from runtime.api.domain.test_session_message_support import (
    ACK_GRACE,
    NATIVE_WAKE_SESSION_ID,
    NOW,
    message_connection,
    park_session,
    record_process_gone,
    selector,
    stamp_activity,
)


#: The native died a minute after its last heartbeat, and the sweep runs a
#: minute after that. Both clocks matter: the heartbeat is recent enough that
#: liveness still reads ``active``, and far too recent for the silence window
#: to have closed, so nothing but the observed death can authorize a wake.
DIED = NOW + timedelta(seconds=60)
SWEEP = DIED + timedelta(seconds=60)


def _send(conn) -> str:
    return send_message(
        conn,
        actor_id=10,
        sender_session_id="s2",
        selector=selector(session_ids=[NATIVE_WAKE_SESSION_ID]),
        body="Never pass this body to a native wake.",
        now=NOW,
    )["message_id"]


def test_the_silence_window_alone_holds_a_recently_quiet_recipient() -> None:
    """The baseline the next test measures against.

    Without the machine's verdict this recipient is an ordinary live-looking
    session one minute into its quiet, and the grace window is right to wait
    it out. Asserting that first is what makes the escalation below
    attributable to the observed death rather than to the clock.
    """
    conn = message_connection()
    _send(conn)
    stamp_activity(conn, when=NOW)
    assert wake_eligible_recipients(conn, now=SWEEP) == []


def test_an_observed_death_escalates_without_waiting_out_the_window() -> None:
    conn = message_connection()
    _send(conn)
    stamp_activity(conn, when=NOW)
    record_process_gone(conn, when=DIED)
    eligible = wake_eligible_recipients(conn, now=SWEEP)
    assert len(eligible) == 1
    candidate = eligible[0]
    # Liveness is the whole reason this gap existed: the heartbeat outlives
    # the process that stopped refreshing it, so the sweep hands an
    # ``active`` recipient back to a hook route that has no process to run.
    assert candidate["liveness"] == "active"
    assert candidate["wake_escalation"] == NATIVE_PROCESS_GONE
    assert (
        wake_operation(candidate["wake_mode"], candidate["liveness"])
        == "message_stopped"
    )


def test_a_tool_call_after_the_death_retires_it() -> None:
    """A replacement process took over, so there is nothing to resume.

    The verdict is not re-derived here; the shared observation reader owns
    that rule, and this holds the wake sweep to it.
    """
    conn = message_connection()
    _send(conn)
    record_process_gone(conn, when=DIED)
    stamp_activity(
        conn,
        when=SWEEP,
        tool_call=(DIED + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    assert wake_eligible_recipients(conn, now=SWEEP) == []


def test_an_observed_exit_retires_an_orphaned_open_tool_call() -> None:
    """A process that exited cannot return the hook its open row promises."""
    conn = message_connection()
    _send(conn)
    stamp_activity(conn, when=NOW)
    record_process_gone(conn, when=DIED)
    # The shared fixture composes no tool-call table, so the open row this
    # test is about arrives with it, in the projection's own column names.
    conn.executescript(
        """
        CREATE TABLE session_tool_calls (
          id INTEGER PRIMARY KEY, session_id TEXT NOT NULL,
          tool_use_id TEXT NOT NULL, tool_name TEXT,
          started_at TEXT NOT NULL, completed_at TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO session_tool_calls "
        "(id,session_id,tool_use_id,tool_name,started_at,completed_at) "
        "VALUES (1,?,?,?,?,NULL)",
        (
            NATIVE_WAKE_SESSION_ID,
            "use-1",
            "Bash",
            NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
        ),
    )
    conn.commit()
    assert (
        wake_eligible_recipients(conn, now=SWEEP)[0]["wake_escalation"]
        == NATIVE_PROCESS_GONE
    )


@pytest.mark.parametrize(
    ("executor", "surface", "version"),
    [
        ("claude-code", "claude-cli", "2.1.238"),
        ("codex", "codex-cli", "0.148.0a15"),
        ("cursor", "cursor-cli", "2026.08.11"),
    ],
)
def test_a_clean_parked_exit_is_quiet_for_alarms_but_due_for_delivery(
    executor,
    surface,
    version,
) -> None:
    conn = message_connection()
    conn.execute(
        "UPDATE harness_sessions SET executor=?,executor_surface=?,executor_version=? "
        "WHERE session_id=?",
        (executor, surface, version, NATIVE_WAKE_SESSION_ID),
    )
    # The connected machine declares the same native resume driver.
    conn.execute(
        "INSERT INTO session_relays (relay_id,actor_id,machine_id,hostname,"
        "relay_version,surface_versions,project_checkouts,first_seen_at,"
        "last_seen_at,connected_until,state) VALUES "
        "('machine:m4',10,'m4','relay','0.1.1',?,'[1]',?,?,?,'active')",
        (
            json.dumps({surface: version}),
            NOW.isoformat(),
            NOW.isoformat(),
            (SWEEP + timedelta(hours=1)).isoformat(),
        ),
    )
    park_session(conn)
    conn.execute(
        "UPDATE harness_sessions SET turn_posture='waiting',turn_posture_at=? "
        "WHERE session_id=?",
        (NOW.isoformat(), NATIVE_WAKE_SESSION_ID),
    )
    conn.commit()
    _send(conn)
    record_process_gone(conn, when=DIED)
    row = dict(
        conn.execute(
            "SELECT * FROM harness_sessions WHERE session_id=?",
            (NATIVE_WAKE_SESSION_ID,),
        ).fetchone()
    )
    assert current_native_process_observation(row) is None
    assert current_native_process_observation(row, include_expected_exit=True)
    from yoke_core.domain.steering_fleet_report_delivery_states import (
        AWAITING_ATTEMPT,
        delivery_state,
    )

    row["open_tool_call_since"] = NOW.isoformat()
    assert (
        delivery_state(
            row,
            result_code="",
            sent_at=NOW.isoformat(),
            grace=ACK_GRACE,
            sla=ACK_GRACE,
            current=SWEEP,
        )
        == AWAITING_ATTEMPT
    )
    candidate = wake_eligible_recipients(conn, now=SWEEP)[0]
    assert candidate["wake_escalation"] == NATIVE_PROCESS_GONE
    assert candidate["wake_mode"] == "waiting"


def test_the_window_still_spaces_repeat_wakes_apart() -> None:
    """No waiting before the first wake; the usual spacing after it."""
    conn = message_connection()
    _send(conn)
    stamp_activity(conn, when=NOW)
    record_process_gone(conn, when=DIED)
    conn.execute(
        "UPDATE session_message_recipients SET wake_attempt_count=1,last_wake_at=?",
        (SWEEP.strftime("%Y-%m-%dT%H:%M:%SZ"),),
    )
    conn.commit()
    assert wake_eligible_recipients(conn, now=SWEEP + timedelta(seconds=1)) == []
    later = SWEEP + ACK_GRACE
    stamp_activity(conn, when=later - timedelta(seconds=30))
    record_process_gone(conn, when=later - timedelta(seconds=15))
    assert len(wake_eligible_recipients(conn, now=later)) == 1


def test_a_starved_route_keeps_its_own_reason() -> None:
    """The two absences stay distinguishable on the receipt.

    An operator reading the row has to be able to tell a death somebody
    observed from a silence the sweep inferred, because only one of them
    says anything about the machine.
    """
    conn = message_connection()
    _send(conn)
    stamp_activity(conn, when=NOW + ACK_GRACE + timedelta(seconds=1))
    eligible = wake_eligible_recipients(
        conn, now=NOW + ACK_GRACE + timedelta(seconds=1)
    )
    assert len(eligible) == 1
    assert eligible[0]["wake_escalation"] == STARVED_HOOK_ROUTE
