"""Launch terminality closes instruction delivery without resurrection."""

from __future__ import annotations

import pytest

from yoke_core.domain.session_launch_deadlines import settle_launch_deadlines
from yoke_core.domain.session_launch_execution import (
    claim_assigned_launch,
    reconcile_launch,
    report_launch_attempt,
)
from yoke_core.domain.session_launch_registration import (
    complete_launch_for_message,
    prepare_launch_registration,
)
from yoke_core.domain.session_launch_requests import cancel_launch, retry_launch
from yoke_core.domain.session_launch_store import get_launch, update_launch
from yoke_core.domain.session_launch_types import SessionLaunchError
from yoke_core.domain.session_message_delivery import (
    complete_hook_lease,
)
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    authorization,
    launch_connection,
)


def _registered_launch(conn, *, key: str):
    launch = assigned_launch(conn, key=key)
    claim = claim_assigned_launch(
        conn,
        launch_id=launch.launch_id,
        relay_id="relay-1",
        machine_id="machine-1",
        now=NOW,
    )
    session_id = f"session-{key}"
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
    return launch, session_id


def _delivery_state(conn, message_id: str) -> tuple[str | None, str]:
    message = conn.execute(
        "SELECT cancellation_reason FROM session_messages WHERE message_id=?",
        (message_id,),
    ).fetchone()
    recipient = conn.execute(
        "SELECT state FROM session_message_recipients WHERE message_id=?",
        (message_id,),
    ).fetchone()
    return message[0], recipient[0]


def test_cancelled_launch_closes_an_active_hook_lease() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch, session_id = _registered_launch(conn, key="cancel-with-lease")
    lease_id = "active-hook-lease"
    conn.execute(
        "UPDATE session_message_recipients SET injection_lease_id=?, "
        "injection_leased_at='2026-08-22T12:00:31Z', "
        "injection_lease_expires_at='2026-08-22T12:01:01Z' WHERE message_id=?",
        (lease_id, launch.message_id),
    )
    conn.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id,message_id,target_session_id,attempt_kind,adapter_revision,"
        "lease_id,started_at,evidence) VALUES (?,?,?,?,?,?,?,?)",
        (
            "active-hook-attempt",
            launch.message_id,
            session_id,
            "hook",
            "session-message-hook-v1",
            lease_id,
            "2026-08-22T12:00:31Z",
            "{}",
        ),
    )
    conn.commit()

    cancelled = cancel_launch(
        conn,
        launch_id=launch.launch_id,
        auth=authorization(),
        now="2026-08-22T12:00:32Z",
    )
    completed = complete_hook_lease(
        conn,
        lease_id=lease_id,
        injected=True,
        result="injected",
    )

    assert cancelled.state == "cancelled"
    assert completed == 0
    assert get_launch(conn, launch.launch_id).state == "cancelled"
    assert _delivery_state(conn, launch.message_id) == (
        "launch_cancelled",
        "cancelled",
    )
    attempt = conn.execute(
        "SELECT result_code FROM session_message_attempts WHERE lease_id=?",
        (lease_id,),
    ).fetchone()
    assert attempt[0] == "launch_cancelled"


def test_cancelled_native_create_reconciliation_binds_the_registered_session() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch = assigned_launch(conn, key="cancel-native-create")
    claim = claim_assigned_launch(
        conn,
        launch_id=launch.launch_id,
        relay_id="relay-1",
        machine_id="machine-1",
        now=NOW,
    )
    cancelled = cancel_launch(
        conn,
        launch_id=launch.launch_id,
        auth=authorization(),
        now="2026-08-22T12:00:10Z",
    )
    late = report_launch_attempt(
        conn,
        launch_id=launch.launch_id,
        lease_id=claim.lease_id,
        result_code="native_created",
        native_session_id="late-native-session",
        now="2026-08-22T12:00:20Z",
    )
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id,project_id,executor_surface,executor_version,machine_id,model) "
        "VALUES ('late-native-session',10,'codex-cli','0.148.0a15','machine-1','gpt-5')"
    )
    conn.commit()

    with pytest.raises(SessionLaunchError) as refused:
        prepare_launch_registration(
            conn,
            launch_id=launch.launch_id,
            attestation=claim.attestation,
            session_id="late-native-session",
            now="2026-08-22T12:00:21Z",
        )

    assert cancelled.state == "outcome_unknown"
    assert late.state == "outcome_unknown"
    assert late.result_code == "late_native_requires_reconciliation"
    assert refused.value.code == "invalid_state"
    assert get_launch(conn, launch.launch_id).state == "outcome_unknown"
    closed = conn.execute(
        "SELECT cancellation_reason,cancelled_at FROM session_messages "
        "WHERE message_id=?",
        (launch.message_id,),
    ).fetchone()
    assert tuple(closed) == ("launch_outcome_unknown", "2026-08-22T12:00:10Z")

    reconciled = reconcile_launch(
        conn,
        launch_id=launch.launch_id,
        auth=authorization(),
        observed_native_id="late-native-session",
        now="2026-08-22T12:00:22Z",
    )
    assert reconciled.state == "awaiting_registration"
    assert reconciled.native_session_id == "late-native-session"
    assert reconciled.registered_session_id == "late-native-session"
    assert reconciled.result_code == "registration_bound"
    assert reconciled.attestation_consumed_at == "2026-08-22T12:00:22Z"
    recipient = conn.execute(
        "SELECT session_id,state FROM session_message_recipients WHERE message_id=?",
        (launch.message_id,),
    ).fetchone()
    assert tuple(recipient) == ("late-native-session", "pending")

    injection = prepare_launch_registration(
        conn,
        launch_id=launch.launch_id,
        attestation=claim.attestation,
        session_id="late-native-session",
        now="2026-08-22T12:00:23Z",
    )
    assert injection.session_id == "late-native-session"
    assert injection.message_id == launch.message_id


def test_deadline_expiry_closes_launch_instruction() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch = assigned_launch(conn, key="expire-assigned")

    changed = settle_launch_deadlines(conn, now="2026-08-22T12:11:00Z")

    assert [row.launch_id for row in changed] == [launch.launch_id]
    assert get_launch(conn, launch.launch_id).state == "expired"
    message = conn.execute(
        "SELECT cancellation_reason FROM session_messages WHERE message_id=?",
        (launch.message_id,),
    ).fetchone()
    assert message[0] == "launch_expired"


def test_retry_reopens_message_without_reactivating_an_old_recipient() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch, session_id = _registered_launch(conn, key="retry-registration")
    conn.execute(
        "UPDATE session_message_recipients SET state='injected', injection_count=1, "
        "last_injected_at='2026-08-22T12:00:32Z', wake_attempt_count=2, "
        "last_wake_at='2026-08-22T12:00:32Z' WHERE message_id=?",
        (launch.message_id,),
    )
    conn.commit()
    settle_launch_deadlines(conn, now="2026-08-22T12:11:00Z")
    assert _delivery_state(conn, launch.message_id) == ("launch_failed", "cancelled")
    reconcile_launch(
        conn,
        launch_id=launch.launch_id,
        auth=authorization(),
        observed_native_id=None,
        now="2026-08-22T12:11:00Z",
    )

    retried = retry_launch(
        conn,
        launch_id=launch.launch_id,
        auth=authorization(),
        now="2026-08-22T12:11:01Z",
    )
    claim = claim_assigned_launch(
        conn,
        launch_id=retried.launch_id,
        relay_id="relay-1",
        machine_id="machine-1",
        now="2026-08-22T12:11:02Z",
    )
    rebound = report_launch_attempt(
        conn,
        launch_id=retried.launch_id,
        lease_id=claim.lease_id,
        result_code="native_created",
        native_session_id=session_id,
        now="2026-08-22T12:11:03Z",
    )

    assert rebound.registered_session_id == session_id
    assert rebound.result_code == "registration_bound"
    assert _delivery_state(conn, launch.message_id) == (None, "pending")
    reset = conn.execute(
        "SELECT injection_count,last_injected_at,wake_attempt_count,"
        "last_wake_at,wake_after FROM session_message_recipients "
        "WHERE message_id=?",
        (launch.message_id,),
    ).fetchone()
    assert tuple(reset[:4]) == (0, None, 0, None)
    assert reset[4] == "2026-08-22T12:11:03Z"
    assert reset[4] != retried.deadline_at
    assert rebound.deadline_at == retried.deadline_at


@pytest.mark.parametrize("terminal_state", ["failed", "expired", "outcome_unknown"])
def test_late_message_completion_cannot_resurrect_terminal_launch(
    terminal_state: str,
) -> None:
    conn = launch_connection()
    add_relay(conn)
    launch, session_id = _registered_launch(conn, key=terminal_state)
    conn.execute(
        "UPDATE session_message_recipients SET state='injected' WHERE message_id=?",
        (launch.message_id,),
    )
    update_launch(
        conn,
        launch.launch_id,
        state=terminal_state,
        completed_at="2026-08-22T12:00:32Z",
        result_code=f"test_{terminal_state}",
    )
    conn.commit()

    completed = complete_launch_for_message(
        conn,
        message_id=launch.message_id,
        session_id=session_id,
        now="2026-08-22T12:00:33Z",
    )

    assert completed and completed.state == terminal_state
    assert get_launch(conn, launch.launch_id).state == terminal_state
    assert _delivery_state(conn, launch.message_id) == (
        f"launch_{terminal_state}",
        "cancelled",
    )
