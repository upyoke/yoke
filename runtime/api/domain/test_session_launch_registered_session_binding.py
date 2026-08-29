"""Launch delivery recovery when the native session registers first."""

from __future__ import annotations

import json

from yoke_core.domain.session_launch_execution import (
    claim_assigned_launch,
    reconcile_launch,
    report_launch_attempt,
)
from yoke_core.domain.session_launch_registration import (
    complete_launch_for_message,
    prepare_launch_registration,
)
from yoke_core.domain.session_launch_store import get_launch
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    authorization,
    launch_connection,
)


def _claim(conn, *, key: str):
    launch = assigned_launch(conn, key=key)
    claim = claim_assigned_launch(
        conn,
        launch_id=launch.launch_id,
        relay_id="relay-1",
        machine_id="machine-1",
        now=NOW,
    )
    return launch, claim


def _register(
    conn,
    session_id: str,
    *,
    surface: str = "codex-cli",
    machine_id: str = "machine-1",
) -> None:
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, project_id, executor_surface, executor_version, machine_id, model) "
        "VALUES (?, 10, ?, '0.148.0a15', ?, 'gpt-5')",
        (session_id, surface, machine_id),
    )
    conn.commit()


def _recipient(conn, message_id: str):
    return conn.execute(
        "SELECT session_id,state,wake_after FROM session_message_recipients "
        "WHERE message_id=?",
        (message_id,),
    ).fetchone()


def _inject_through_ordinary_delivery(conn, launch, session_id: str):
    conn.execute(
        "UPDATE session_message_recipients SET state='injected',injection_count=1 "
        "WHERE message_id=? AND session_id=?",
        (launch.message_id, session_id),
    )
    conn.commit()
    return complete_launch_for_message(
        conn,
        message_id=launch.message_id,
        session_id=session_id,
        now="2026-08-22T12:00:32Z",
    )


def test_native_report_binds_a_session_that_registered_before_correlation() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch, claim = _claim(conn, key="registered-before-report")
    _register(conn, "native-session")

    bound = report_launch_attempt(
        conn,
        launch_id=launch.launch_id,
        lease_id=claim.lease_id,
        result_code="native_created",
        native_session_id="native-session",
        now="2026-08-22T12:00:30Z",
    )

    assert bound.state == "awaiting_registration"
    assert bound.native_session_id == bound.registered_session_id == "native-session"
    assert bound.result_code == "registration_bound"
    assert bound.attestation_consumed_at == "2026-08-22T12:00:30Z"
    assert tuple(_recipient(conn, launch.message_id)) == (
        "native-session",
        "pending",
        "2026-08-22T12:00:30Z",
    )
    assert _inject_through_ordinary_delivery(conn, launch, "native-session").state == (
        "succeeded"
    )


def test_reconciliation_reopens_and_routes_the_stranded_instruction() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch, claim = _claim(conn, key="reconciled-existing-session")
    uncertain = report_launch_attempt(
        conn,
        launch_id=launch.launch_id,
        lease_id=claim.lease_id,
        result_code="outcome_unknown",
        evidence={"result_code": "identity_parse_failed"},
        now="2026-08-22T12:00:20Z",
    )
    assert uncertain.state == "outcome_unknown"
    cancelled = conn.execute(
        "SELECT cancellation_reason FROM session_messages WHERE message_id=?",
        (launch.message_id,),
    ).fetchone()
    assert cancelled[0] == "launch_outcome_unknown"
    _register(conn, "reconciled-session")

    bound = reconcile_launch(
        conn,
        launch_id=launch.launch_id,
        auth=authorization(),
        observed_native_id="reconciled-session",
        now="2026-08-22T12:00:30Z",
    )

    assert (
        bound.native_session_id == bound.registered_session_id == ("reconciled-session")
    )
    assert bound.result_code == "registration_bound"
    assert tuple(_recipient(conn, launch.message_id)) == (
        "reconciled-session",
        "pending",
        "2026-08-22T12:00:30Z",
    )
    reopened = conn.execute(
        "SELECT cancellation_reason FROM session_messages WHERE message_id=?",
        (launch.message_id,),
    ).fetchone()
    assert reopened[0] is None


def test_attested_registration_recovers_a_missing_native_identity() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch, claim = _claim(conn, key="attested-identity")
    uncertain = report_launch_attempt(
        conn,
        launch_id=launch.launch_id,
        lease_id=claim.lease_id,
        result_code="outcome_unknown",
        evidence={"result_code": "identity_parse_failed"},
        now="2026-08-22T12:00:20Z",
    )
    assert uncertain.native_session_id is None
    _register(conn, "attested-session")

    injection = prepare_launch_registration(
        conn,
        launch_id=launch.launch_id,
        attestation=claim.attestation,
        session_id="attested-session",
        now="2026-08-22T12:00:30Z",
    )
    bound = get_launch(conn, launch.launch_id)

    assert injection.session_id == "attested-session"
    assert bound.state == "awaiting_registration"
    assert bound.native_session_id == bound.registered_session_id == "attested-session"
    assert bound.result_code == "registration_bound"
    assert bound.attestation_consumed_at == "2026-08-22T12:00:30Z"
    attempt = conn.execute(
        "SELECT native_session_id FROM session_launch_attempts WHERE launch_id=?",
        (launch.launch_id,),
    ).fetchone()
    assert attempt[0] == "attested-session"
    assert tuple(_recipient(conn, launch.message_id)) == (
        "attested-session",
        "pending",
        launch.deadline_at,
    )
    reopened = conn.execute(
        "SELECT cancellation_reason FROM session_messages WHERE message_id=?",
        (launch.message_id,),
    ).fetchone()
    assert reopened[0] is None


def test_existing_session_mismatch_is_visible_without_losing_native_evidence() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch, claim = _claim(conn, key="registered-surface-mismatch")
    _register(conn, "wrong-surface", surface="codex-desktop")

    awaiting = report_launch_attempt(
        conn,
        launch_id=launch.launch_id,
        lease_id=claim.lease_id,
        result_code="native_created",
        native_session_id="wrong-surface",
        now="2026-08-22T12:00:30Z",
    )

    assert awaiting.state == "awaiting_registration"
    assert awaiting.native_session_id == "wrong-surface"
    assert awaiting.registered_session_id is None
    assert awaiting.result_code == "surface_mismatch"
    assert json.loads(awaiting.result_evidence)["registration_refusal_code"] == (
        "surface_mismatch"
    )
    assert _recipient(conn, launch.message_id) is None
    assert get_launch(conn, launch.launch_id).native_session_id == "wrong-surface"
