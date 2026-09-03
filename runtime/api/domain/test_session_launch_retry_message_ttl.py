"""Retry realigns the instruction TTL so a late bind still delivers."""

from __future__ import annotations

from yoke_core.domain.session_launch_execution import (
    claim_assigned_launch,
    reconcile_launch,
    report_launch_attempt,
)
from yoke_core.domain.session_launch_registration import complete_launch_injection
from yoke_core.domain.session_launch_requests import retry_launch
from yoke_core.domain.session_launch_store import parse_time
from yoke_core.domain.session_message_delivery import expire_due_recipients
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    authorization,
    launch_connection,
)


def _register(conn, session_id: str) -> None:
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, project_id, executor_surface, executor_version, machine_id, model) "
        "VALUES (?, 10, 'codex-cli', '0.148.0a15', 'machine-1', 'gpt-5')",
        (session_id,),
    )
    conn.commit()


def _message_expiry(conn, message_id: str) -> str:
    return conn.execute(
        "SELECT expires_at FROM session_messages WHERE message_id=?",
        (message_id,),
    ).fetchone()[0]


def test_bind_after_retry_realigns_message_ttl_so_recipient_survives_sweep() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch = assigned_launch(conn, key="retry-ttl")
    original_expiry = _message_expiry(conn, launch.message_id)

    # First attempt cannot bind and the launch is reconciled to failed.
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
        result_code="outcome_unknown",
        evidence={"result_code": "identity_parse_failed"},
        now="2026-08-22T12:00:20Z",
    )
    reconcile_launch(
        conn,
        launch_id=launch.launch_id,
        auth=authorization(),
        observed_native_id=None,
        now="2026-08-22T12:09:00Z",
    )

    # Retry resets the launch deadline but leaves the message pinned to the
    # original deadline, which is exactly the drift the bind must repair.
    retried = retry_launch(
        conn,
        launch_id=launch.launch_id,
        auth=authorization(),
        now="2026-08-22T12:11:00Z",
    )
    assert _message_expiry(conn, launch.message_id) == original_expiry
    assert retried.deadline_at != original_expiry

    _register(conn, "retry-native")
    claim_two = claim_assigned_launch(
        conn,
        launch_id=launch.launch_id,
        relay_id="relay-1",
        machine_id="machine-1",
        now="2026-08-22T12:11:01Z",
    )
    report_launch_attempt(
        conn,
        launch_id=launch.launch_id,
        lease_id=claim_two.lease_id,
        result_code="native_created",
        native_session_id="retry-native",
        now="2026-08-22T12:12:00Z",
    )

    # Binding realigned the message TTL to the fresh deadline, so the expiry
    # sweep run past the ORIGINAL deadline leaves the recipient pending and
    # injectable rather than flipping it to expired within a second.
    assert _message_expiry(conn, launch.message_id) == retried.deadline_at
    expire_due_recipients(conn, now=parse_time("2026-08-22T12:12:30Z"))
    recipient = conn.execute(
        "SELECT state FROM session_message_recipients WHERE message_id=?",
        (launch.message_id,),
    ).fetchone()
    assert recipient[0] == "pending"

    completed = complete_launch_injection(
        conn,
        launch_id=launch.launch_id,
        session_id="retry-native",
        injected=True,
        now="2026-08-22T12:12:31Z",
    )
    assert completed.state == "succeeded"
