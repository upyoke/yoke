"""A bound, working launch session is delivered, not failed, at its deadline."""

from __future__ import annotations

from yoke_core.domain.session_launch_bound_liveness import bound_session_delivered
from yoke_core.domain.session_launch_deadlines import settle_launch_deadlines
from yoke_core.domain.session_launch_execution import (
    claim_assigned_launch,
    report_launch_attempt,
)
from yoke_core.domain.session_launch_registration import prepare_launch_registration
from yoke_core.domain.session_launch_store import get_launch
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    launch_connection,
)


def _bound_launch(conn, *, key: str, session_id: str):
    launch = assigned_launch(conn, key=key)
    claim = claim_assigned_launch(
        conn,
        launch_id=launch.launch_id,
        relay_id="relay-1",
        machine_id="machine-1",
        now=NOW,
    )
    report_launch_attempt(
        conn,
        launch_id=launch.launch_id,
        lease_id=claim.lease_id,
        result_code="native_created",
        native_session_id=session_id,
        now="2026-08-22T12:00:30Z",
    )
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, project_id, executor_surface, executor_version, machine_id, model) "
        "VALUES (?, 10, 'codex-cli', '0.148.0a15', 'machine-1', 'gpt-5')",
        (session_id,),
    )
    conn.commit()
    prepare_launch_registration(
        conn,
        launch_id=launch.launch_id,
        attestation=claim.attestation,
        session_id=session_id,
        now="2026-08-22T12:00:31Z",
    )
    return launch


def _hold_item_claim(conn, session_id: str) -> None:
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, scope, claim_type, claimed_at, last_heartbeat) "
        "VALUES (?, 'item', '{\"item_id\":1}', 'exclusive', ?, ?)",
        (session_id, NOW, NOW),
    )
    conn.commit()


def test_bound_session_delivered_true_when_session_holds_a_work_claim() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch = _bound_launch(conn, key="held-claim", session_id="worker-session")
    _hold_item_claim(conn, "worker-session")

    assert bound_session_delivered(
        conn, get_launch(conn, launch.launch_id), now="2026-08-22T12:20:00Z"
    )


def test_bound_session_delivered_false_when_session_ended_and_claimless() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch = _bound_launch(conn, key="ended", session_id="ended-session")
    conn.execute(
        "UPDATE harness_sessions SET ended_at=? WHERE session_id=?",
        ("2026-08-22T12:05:00Z", "ended-session"),
    )
    conn.commit()

    assert not bound_session_delivered(
        conn, get_launch(conn, launch.launch_id), now="2026-08-22T12:20:00Z"
    )


def test_deadline_closes_a_working_bound_launch_delivered_not_failed() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch = _bound_launch(conn, key="working", session_id="working-session")
    _hold_item_claim(conn, "working-session")

    changed = settle_launch_deadlines(conn, now="2026-08-22T12:20:00Z")

    closed = get_launch(conn, launch.launch_id)
    assert [row.launch_id for row in changed] == [launch.launch_id]
    assert closed.state == "succeeded"
    assert closed.result_code == "registered_and_claimed"
    # The instruction message is left alone: a delivered launch is not a
    # cancelled one, so the session card does not read "Latest: expired".
    message = conn.execute(
        "SELECT cancellation_reason FROM session_messages WHERE message_id=?",
        (launch.message_id,),
    ).fetchone()
    assert message[0] is None
    recipient = conn.execute(
        "SELECT state FROM session_message_recipients WHERE message_id=?",
        (launch.message_id,),
    ).fetchone()
    assert recipient[0] in {"pending", "injected"}


def test_deadline_still_fails_an_unclaimed_idle_bound_launch() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch = _bound_launch(conn, key="idle", session_id="idle-session")

    settle_launch_deadlines(conn, now="2026-08-22T12:20:00Z")

    closed = get_launch(conn, launch.launch_id)
    assert closed.state == "failed"
    assert closed.result_code == "registration_deadline"
