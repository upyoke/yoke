"""Focused crash-boundary and attestation tests for session creation."""

from __future__ import annotations

import pytest

from yoke_contracts.session_control.launch_bootstrap import native_launch_bootstrap
from yoke_core.domain.session_launch_deadlines import settle_launch_deadlines
from yoke_core.domain.session_launch_execution import (
    claim_assigned_launch,
    reconcile_launch,
    report_launch_attempt,
)
from yoke_core.domain.session_launch_registration import (
    complete_launch_for_message,
    complete_launch_injection,
    prepare_launch_registration,
)
from yoke_core.domain.session_launch_requests import retry_launch
from yoke_core.domain.session_launch_store import get_launch
from yoke_core.domain.session_launch_types import SessionLaunchError
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    authorization,
    launch_connection,
)


def test_claim_separates_bootstrap_body_and_stores_only_attestation_hash() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch = assigned_launch(conn, instructions="Sensitive instruction body")

    claim = claim_assigned_launch(
        conn,
        launch_id=launch.launch_id,
        relay_id="relay-1",
        machine_id="machine-1",
        now=NOW,
    )

    assert claim.bootstrap_prompt == (native_launch_bootstrap(launch.launch_id))
    assert "Sensitive instruction body" not in claim.bootstrap_prompt
    assert claim.lease_expires_at == "2026-08-22T12:05:00Z"
    stored = get_launch(conn, launch.launch_id)
    assert stored.attestation_hash.startswith("sha256:")
    assert claim.attestation not in stored.attestation_hash
    attempt = conn.execute(
        "SELECT lease_id, attempt_number FROM session_launch_attempts"
    ).fetchone()
    assert tuple(attempt) == (claim.lease_id, 1)


def test_lost_native_outcome_requires_reconciliation_before_retry() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch = assigned_launch(conn)
    claim_assigned_launch(
        conn,
        launch_id=launch.launch_id,
        relay_id="relay-1",
        machine_id="machine-1",
        now=NOW,
    )

    changed = settle_launch_deadlines(conn, now="2026-08-22T12:05:01Z")
    assert changed[0].state == "outcome_unknown"
    with pytest.raises(SessionLaunchError) as blocked:
        retry_launch(
            conn,
            launch_id=launch.launch_id,
            auth=authorization(),
            now="2026-08-22T12:05:02Z",
        )
    assert blocked.value.code == "reconcile_required"

    reconciled = reconcile_launch(
        conn,
        launch_id=launch.launch_id,
        auth=authorization(),
        observed_native_id=None,
        now="2026-08-22T12:05:03Z",
    )
    assert reconciled.result_code == "reconciled_not_created"
    retried = retry_launch(
        conn,
        launch_id=launch.launch_id,
        auth=authorization(),
        now="2026-08-22T12:05:04Z",
    )
    second = claim_assigned_launch(
        conn,
        launch_id=retried.launch_id,
        relay_id="relay-1",
        machine_id="machine-1",
        now="2026-08-22T12:05:05Z",
    )
    assert second.attempt_number == 2


def _awaiting_launch(conn, *, key: str = "binding"):
    launch = assigned_launch(conn, key=key)
    claim = claim_assigned_launch(
        conn,
        launch_id=launch.launch_id,
        relay_id="relay-1",
        machine_id="machine-1",
        now=NOW,
    )
    awaiting = report_launch_attempt(
        conn,
        launch_id=launch.launch_id,
        lease_id=claim.lease_id,
        result_code="native_created",
        native_session_id=f"session-{key}",
        adapter_revision="adapter-1",
        evidence={"duration_ms": 40, "exit_code": 0},
        now="2026-08-22T12:00:30Z",
    )
    return awaiting, claim


def _register_candidate(
    conn,
    *,
    session_id: str,
    surface: str = "codex-cli",
    machine_id: str = "machine-1",
    model: str = "gpt-5",
) -> None:
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, project_id, executor_surface, executor_version, machine_id, model) "
        "VALUES (?, 10, ?, '0.148.0a15', ?, ?)",
        (session_id, surface, machine_id, model),
    )
    conn.commit()


def test_registration_is_single_use_and_success_requires_injection_completion() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch, claim = _awaiting_launch(conn)
    _register_candidate(conn, session_id="session-binding")

    injection = prepare_launch_registration(
        conn,
        launch_id=launch.launch_id,
        attestation=claim.attestation,
        session_id="session-binding",
        now="2026-08-22T12:00:31Z",
    )

    assert injection.body == "Inspect the current work and report evidence."
    assert get_launch(conn, launch.launch_id).state == "awaiting_registration"
    receipt = conn.execute(
        "SELECT state FROM session_message_recipients WHERE message_id = ?",
        (launch.message_id,),
    ).fetchone()
    assert receipt[0] == "pending"
    with pytest.raises(SessionLaunchError) as replay:
        prepare_launch_registration(
            conn,
            launch_id=launch.launch_id,
            attestation=claim.attestation,
            session_id="session-binding",
            now="2026-08-22T12:00:32Z",
        )
    assert replay.value.code == "attestation_consumed"

    completed = complete_launch_injection(
        conn,
        launch_id=launch.launch_id,
        session_id="session-binding",
        injected=True,
        now="2026-08-22T12:00:33Z",
    )
    assert completed.state == "succeeded"
    assert (
        conn.execute(
            "SELECT state FROM session_message_recipients WHERE message_id = ?",
            (launch.message_id,),
        ).fetchone()[0]
        == "injected"
    )


def test_dropped_first_hook_recovers_through_ordinary_message_delivery() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch, claim = _awaiting_launch(conn, key="render-crash")
    _register_candidate(conn, session_id="session-render-crash")
    prepare_launch_registration(
        conn,
        launch_id=launch.launch_id,
        attestation=claim.attestation,
        session_id="session-render-crash",
        now="2026-08-22T12:00:31Z",
    )
    complete_launch_injection(
        conn,
        launch_id=launch.launch_id,
        session_id="session-render-crash",
        injected=False,
        now="2026-08-22T12:00:32Z",
    )
    assert get_launch(conn, launch.launch_id).state == "awaiting_registration"

    conn.execute(
        "UPDATE session_message_recipients SET state='injected', injection_count=1 "
        "WHERE message_id=? AND session_id=?",
        (launch.message_id, "session-render-crash"),
    )
    conn.commit()
    completed = complete_launch_for_message(
        conn,
        message_id=launch.message_id,
        session_id="session-render-crash",
        now="2026-08-22T12:00:33Z",
    )
    assert completed and completed.state == "succeeded"
    assert (
        conn.execute(
            "SELECT injection_count FROM session_message_recipients WHERE message_id=?",
            (launch.message_id,),
        ).fetchone()[0]
        == 1
    )


@pytest.mark.parametrize(
    "session_id,surface,machine_id,model,code",
    [
        ("session-surface", "codex-desktop", "machine-1", "gpt-5", "surface_mismatch"),
        ("session-machine", "codex-cli", "wrong", "gpt-5", "machine_mismatch"),
        (
            "different-native",
            "codex-cli",
            "machine-1",
            "gpt-5",
            "native_session_mismatch",
        ),
    ],
)
def test_registration_refuses_exact_binding_mismatches(
    session_id: str,
    surface: str,
    machine_id: str,
    model: str,
    code: str,
) -> None:
    conn = launch_connection()
    add_relay(conn)
    launch, claim = _awaiting_launch(conn, key=code)
    candidate_id = (
        f"session-{code}" if code != "native_session_mismatch" else session_id
    )
    _register_candidate(
        conn,
        session_id=candidate_id,
        surface=surface,
        machine_id=machine_id,
        model=model,
    )

    with pytest.raises(SessionLaunchError) as refused:
        prepare_launch_registration(
            conn,
            launch_id=launch.launch_id,
            attestation=claim.attestation,
            session_id=candidate_id,
            now="2026-08-22T12:00:31Z",
        )
    assert refused.value.code == code
    assert get_launch(conn, launch.launch_id).attestation_consumed_at is None


def test_late_registration_fails_and_preserves_known_native_id() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch, claim = _awaiting_launch(conn, key="late")
    _register_candidate(conn, session_id="session-late")

    with pytest.raises(SessionLaunchError) as refused:
        prepare_launch_registration(
            conn,
            launch_id=launch.launch_id,
            attestation=claim.attestation,
            session_id="session-late",
            now="2026-08-22T12:11:00Z",
        )
    assert refused.value.code == "late_registration"
    failed = get_launch(conn, launch.launch_id)
    assert failed.state == "failed"
    assert failed.native_session_id == "session-late"


def test_explicit_failure_is_retryable_but_uncertain_report_is_not() -> None:
    conn = launch_connection()
    add_relay(conn)
    safe = assigned_launch(conn, key="safe-failure")
    safe_claim = claim_assigned_launch(
        conn,
        launch_id=safe.launch_id,
        relay_id="relay-1",
        machine_id="machine-1",
        now=NOW,
    )
    failed = report_launch_attempt(
        conn,
        launch_id=safe.launch_id,
        lease_id=safe_claim.lease_id,
        result_code="not_created",
        evidence={"exit_code": 1},
        now="2026-08-22T12:00:20Z",
    )
    assert failed.result_code == "native_create_failed"
    assert (
        retry_launch(
            conn,
            launch_id=safe.launch_id,
            auth=authorization(),
            now="2026-08-22T12:00:21Z",
        ).state
        == "assigned"
    )

    uncertain = assigned_launch(conn, key="uncertain")
    uncertain_claim = claim_assigned_launch(
        conn,
        launch_id=uncertain.launch_id,
        relay_id="relay-1",
        machine_id="machine-1",
        now=NOW,
    )
    unknown = report_launch_attempt(
        conn,
        launch_id=uncertain.launch_id,
        lease_id=uncertain_claim.lease_id,
        result_code="native_created",
        native_session_id=None,
        now="2026-08-22T12:00:20Z",
    )
    assert unknown.state == "outcome_unknown"
