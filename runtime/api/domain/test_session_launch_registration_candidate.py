"""Registration-first correlation for a supervised native launch."""

from __future__ import annotations

import pytest

from yoke_core.domain.session_launch_execution import (
    claim_assigned_launch,
    reconcile_launch,
    report_launch_attempt,
)
from yoke_core.domain.session_launch_pending_delivery import pending_launch_deliveries
from yoke_core.domain.session_launch_registration import (
    complete_launch_injection,
    prepare_launch_registration,
)
from yoke_core.domain.session_launch_registration_candidate import (
    registered_candidate_for_reconcile,
    reserve_launch_registration_candidate,
)
from yoke_core.domain.session_launch_store import get_launch
from yoke_core.domain.session_relay import report_relay_job
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    authorization,
    relay_connection,
)


SESSION_ID = "87654321-4321-4321-8321-cba987654321"
WORKSPACE = "/project"


def _connection():
    conn = relay_connection()
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN workspace TEXT")
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN episode_started_at TEXT")
    conn.commit()
    return conn


def _claimed_launch(conn, key: str):
    add_relay(conn, surface="claude-cli", version="2.1.238")
    launch = assigned_launch(conn, key=key, surface="claude-cli")
    claim = claim_assigned_launch(
        conn,
        launch_id=launch.launch_id,
        relay_id="relay-1",
        machine_id="machine-1",
        now=NOW,
    )
    report_relay_job(
        conn,
        actor_id=1,
        relay_id="relay-1",
        job_kind="launch",
        job_id=launch.launch_id,
        lease_id=claim.lease_id,
        result_code="progress",
        adapter_revision="claude-native-v7",
        evidence={
            "result_code": "native_spawn_pending",
            "native_launch_phase": "spawn_started",
            "native_launch_pid": 4242,
            "native_launch_workspace": WORKSPACE,
            "native_launch_bound_seconds": 120,
        },
        now="2026-08-22T12:00:01Z",
    )
    return launch, claim


def _register_candidate(
    conn,
    *,
    session_id: str = SESSION_ID,
    workspace: str = WORKSPACE,
    surface: str = "claude-cli",
    machine_id: str = "machine-1",
) -> None:
    conn.execute(
        "INSERT INTO harness_sessions ("
        "session_id,project_id,executor_surface,executor_version,machine_id,model,"
        "workspace,offered_at,episode_started_at) "
        "VALUES (?,10,?,'2.1.238',?,'claude-opus',?,?,?)",
        (
            session_id,
            surface,
            machine_id,
            workspace,
            "2026-08-22T12:00:02Z",
            "2026-08-22T12:00:02Z",
        ),
    )
    conn.commit()


def test_registered_session_binding_remains_deliverable_after_marker_expiry() -> None:
    conn = _connection()
    launch, claim = _claimed_launch(conn, "registration-first")
    _register_candidate(conn)

    progress = report_relay_job(
        conn,
        actor_id=1,
        relay_id="relay-1",
        job_kind="launch",
        job_id=launch.launch_id,
        lease_id=claim.lease_id,
        result_code="progress",
        adapter_revision="claude-native-v7",
        evidence={
            "result_code": "identity_registration_wait",
            "native_launch_workspace": WORKSPACE,
        },
        now="2026-08-22T12:00:03Z",
    )

    assert progress["registration"] == {
        "status": "registered_but_unbound",
        "session_id": SESSION_ID,
        "binding_window_ends_at": "2026-08-22T12:02:00Z",
    }
    reserved = get_launch(conn, launch.launch_id)
    assert reserved.state == "launching"
    assert reserved.native_session_id == SESSION_ID
    assert reserved.registered_session_id is None
    assert reserved.result_code == "registered_but_unbound"
    assert (
        pending_launch_deliveries(conn, (SESSION_ID,), now="2026-08-22T12:00:04Z")[
            SESSION_ID
        ]["status"]
        == "launch_delivery_pending"
    )
    assert (
        pending_launch_deliveries(conn, (SESSION_ID,), now="2026-08-22T12:02:00Z") == {}
    )

    terminal = report_relay_job(
        conn,
        actor_id=1,
        relay_id="relay-1",
        job_kind="launch",
        job_id=launch.launch_id,
        lease_id=claim.lease_id,
        result_code="native_created",
        native_session_id=SESSION_ID,
        adapter_revision="claude-native-v7",
        evidence={"result_code": "registered_but_unbound", "exit_code": 0},
        now="2026-08-22T12:00:04Z",
    )
    bound = get_launch(conn, launch.launch_id)

    assert terminal["state"] == "awaiting_registration"
    assert bound.state == "awaiting_registration"
    assert bound.native_session_id == SESSION_ID
    assert bound.registered_session_id == SESSION_ID
    assert bound.result_code == "registration_bound"

    injection = prepare_launch_registration(
        conn,
        launch_id=launch.launch_id,
        attestation=claim.attestation,
        session_id=SESSION_ID,
        now="2026-08-22T12:00:05Z",
    )

    assert injection.launch_id == launch.launch_id
    assert injection.message_id == launch.message_id
    assert injection.session_id == SESSION_ID
    assert injection.body == "Inspect the current work and report evidence."
    assert get_launch(conn, launch.launch_id).attestation_consumed_at == (
        "2026-08-22T12:00:04Z"
    )

    complete_launch_injection(
        conn,
        launch_id=launch.launch_id,
        session_id=SESSION_ID,
        injected=True,
        now="2026-08-22T12:00:06Z",
    )
    replayed = prepare_launch_registration(
        conn,
        launch_id=launch.launch_id,
        attestation=claim.attestation,
        session_id=SESSION_ID,
        now="2026-08-22T14:00:07Z",
    )

    assert replayed == injection
    assert get_launch(conn, launch.launch_id).state == "succeeded"


@pytest.mark.parametrize(
    ("candidate"),
    (
        {"workspace": "/different-project"},
        {"surface": "codex-cli"},
        {"machine_id": "machine-2"},
    ),
)
def test_registration_candidate_requires_the_spawn_context(candidate) -> None:
    conn = _connection()
    launch, claim = _claimed_launch(conn, f"context-mismatch-{next(iter(candidate))}")
    _register_candidate(conn, **candidate)

    result = reserve_launch_registration_candidate(
        conn,
        launch_id=launch.launch_id,
        lease_id=claim.lease_id,
        now="2026-08-22T12:00:03Z",
    )
    conn.commit()

    assert result == {"status": "registration_pending"}
    assert get_launch(conn, launch.launch_id).native_session_id is None


def test_registration_candidate_excludes_a_session_bound_to_another_launch() -> None:
    conn = _connection()
    launch, claim = _claimed_launch(conn, "binding-conflict")
    _register_candidate(conn)
    other = assigned_launch(conn, key="existing-binding", surface="claude-cli")
    conn.execute(
        "UPDATE session_launches SET native_session_id=? WHERE launch_id=?",
        (SESSION_ID, other.launch_id),
    )
    conn.commit()

    result = reserve_launch_registration_candidate(
        conn,
        launch_id=launch.launch_id,
        lease_id=claim.lease_id,
        now="2026-08-22T12:00:03Z",
    )
    conn.commit()

    assert result == {"status": "registration_pending"}
    assert get_launch(conn, launch.launch_id).native_session_id is None


def test_registration_candidate_does_not_guess_between_matching_sessions() -> None:
    conn = _connection()
    launch, claim = _claimed_launch(conn, "ambiguous-registration")
    _register_candidate(conn)
    _register_candidate(
        conn,
        session_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    )

    result = reserve_launch_registration_candidate(
        conn,
        launch_id=launch.launch_id,
        lease_id=claim.lease_id,
        now="2026-08-22T12:00:03Z",
    )
    conn.commit()

    assert result == {"status": "registration_ambiguous", "candidate_count": 2}
    assert get_launch(conn, launch.launch_id).native_session_id is None


def test_reconcile_adopts_a_session_registered_in_a_closed_window() -> None:
    conn = _connection()
    launch, claim = _claimed_launch(conn, "reconcile-adopt")
    _register_candidate(conn)
    # The relay's pid listing never saw the session and the attempt closed
    # unbound; the launch is now reconcilable.
    report_launch_attempt(
        conn,
        launch_id=launch.launch_id,
        lease_id=claim.lease_id,
        result_code="outcome_unknown",
        evidence={"result_code": "identity_listing_failed"},
        now="2026-08-22T12:00:05Z",
    )
    assert get_launch(conn, launch.launch_id).state == "outcome_unknown"

    # The session that registered inside the (now closed) binding window is
    # still the launch's rightful native, discoverable without a time gate.
    assert (
        registered_candidate_for_reconcile(conn, get_launch(conn, launch.launch_id))
        == SESSION_ID
    )

    bound = reconcile_launch(
        conn,
        launch_id=launch.launch_id,
        auth=authorization(),
        observed_native_id=None,
        now="2026-08-22T12:30:00Z",
    )

    assert bound.native_session_id == bound.registered_session_id == SESSION_ID
    assert bound.result_code == "registration_bound"
    recipient = conn.execute(
        "SELECT session_id, state FROM session_message_recipients WHERE message_id=?",
        (launch.message_id,),
    ).fetchone()
    assert tuple(recipient) == (SESSION_ID, "pending")


def test_reconcile_does_not_adopt_when_no_session_registered_in_window() -> None:
    conn = _connection()
    launch, claim = _claimed_launch(conn, "reconcile-no-candidate")
    report_launch_attempt(
        conn,
        launch_id=launch.launch_id,
        lease_id=claim.lease_id,
        result_code="outcome_unknown",
        evidence={"result_code": "identity_listing_failed"},
        now="2026-08-22T12:00:05Z",
    )

    reconciled = reconcile_launch(
        conn,
        launch_id=launch.launch_id,
        auth=authorization(),
        observed_native_id=None,
        now="2026-08-22T12:30:00Z",
    )

    assert reconciled.state == "failed"
    assert reconciled.result_code == "reconciled_not_created"
    assert reconciled.registered_session_id is None
