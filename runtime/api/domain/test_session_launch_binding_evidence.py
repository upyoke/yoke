"""A launch says what it observed: model labels, refusals, and closures."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.session_launch_binding_evidence import (
    record_registration_refusal,
)
from yoke_core.domain.session_launch_deadlines import settle_launch_deadlines
from yoke_core.domain.session_launch_execution import (
    claim_assigned_launch,
    report_launch_attempt,
)
from yoke_core.domain.session_launch_registration import prepare_launch_registration
from yoke_core.domain.session_launch_store import get_launch
from yoke_core.domain.session_launch_types import SessionLaunchError
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    launch_connection,
)


def _evidence(conn, launch_id: str) -> dict:
    stored = get_launch(conn, launch_id).result_evidence
    return json.loads(stored) if stored else {}


def _awaiting(conn, *, key: str, model: str | None = "gpt-5"):
    launch = assigned_launch(conn, key=key, model=model)
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
        now="2026-08-22T12:00:30Z",
    )
    return awaiting, claim


def _candidate(conn, *, session_id: str, model: str = "gpt-5") -> None:
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, project_id, executor_surface, executor_version, "
        "machine_id, model) VALUES (?, 10, 'codex-cli', '0.148.0a15', "
        "'machine-1', ?)",
        (session_id, model),
    )
    conn.commit()


def test_differing_model_labels_bind_and_are_recorded_rather_than_refused() -> None:
    """The requested selector and the registered model are two vocabularies."""
    conn = launch_connection()
    add_relay(conn)
    launch, claim = _awaiting(conn, key="labels", model="cursor-grok-4.6-high-fast")
    _candidate(conn, session_id="session-labels", model="grok-4.6")

    injection = prepare_launch_registration(
        conn,
        launch_id=launch.launch_id,
        attestation=claim.attestation,
        session_id="session-labels",
        now="2026-08-22T12:00:31Z",
    )

    assert injection.session_id == "session-labels"
    bound = get_launch(conn, launch.launch_id)
    assert bound.registered_session_id == "session-labels"
    evidence = _evidence(conn, launch.launch_id)
    assert evidence["requested_model"] == "cursor-grok-4.6-high-fast"
    assert evidence["registered_model"] == "grok-4.6"


def test_matching_model_labels_record_no_divergence() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch, claim = _awaiting(conn, key="same")
    _candidate(conn, session_id="session-same")

    prepare_launch_registration(
        conn,
        launch_id=launch.launch_id,
        attestation=claim.attestation,
        session_id="session-same",
        now="2026-08-22T12:00:31Z",
    )

    evidence = _evidence(conn, launch.launch_id)
    assert "requested_model" not in evidence
    assert "registered_model" not in evidence


def test_refused_registration_is_written_onto_the_launch_once_per_code() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch, _claim = _awaiting(conn, key="refused")

    record_registration_refusal(
        conn,
        launch_id=launch.launch_id,
        code="surface_mismatch",
        session_id="session-refused",
    )
    first = get_launch(conn, launch.launch_id)
    record_registration_refusal(
        conn,
        launch_id=launch.launch_id,
        code="surface_mismatch",
        session_id="session-refused",
    )
    repeated = get_launch(conn, launch.launch_id)

    evidence = _evidence(conn, launch.launch_id)
    assert evidence["registration_refusal_code"] == "surface_mismatch"
    assert evidence["registration_session_id"] == "session-refused"
    assert repeated.result_evidence == first.result_evidence
    assert repeated.state == "awaiting_registration"


def test_late_registration_records_what_the_server_could_still_observe() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch, claim = _awaiting(conn, key="late-evidence")
    _candidate(conn, session_id="session-late-evidence")

    with pytest.raises(SessionLaunchError):
        prepare_launch_registration(
            conn,
            launch_id=launch.launch_id,
            attestation=claim.attestation,
            session_id="session-late-evidence",
            now="2026-08-22T12:11:00Z",
        )

    evidence = _evidence(conn, launch.launch_id)
    assert evidence["result_code"] == "late_registration"
    assert evidence["closure_reason"] == "registration_after_deadline"
    assert evidence["launch_phase_reached"] == "awaiting_registration"
    assert evidence["registration_session_id"] == "session-late-evidence"


def test_registration_deadline_is_never_a_zero_evidence_verdict() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch, _claim = _awaiting(conn, key="deadline")

    changed = settle_launch_deadlines(conn, now="2026-08-22T12:11:00Z")

    assert [record.result_code for record in changed] == ["registration_deadline"]
    evidence = _evidence(conn, launch.launch_id)
    assert evidence["result_code"] == "registration_deadline"
    assert evidence["closure_reason"] == "deadline_expiry"
    assert evidence["launch_phase_reached"] == "awaiting_registration"
    assert evidence["transport_state"] == "relay_connected"
    assert evidence["relay_id"] == "relay-1"


def test_queued_launch_expiry_also_carries_its_phase() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch = assigned_launch(conn, key="queued-deadline")

    settle_launch_deadlines(conn, now="2026-08-22T12:11:00Z")

    assert get_launch(conn, launch.launch_id).state == "expired"
    evidence = _evidence(conn, launch.launch_id)
    assert evidence["result_code"] == "launch_deadline"
    assert evidence["launch_phase_reached"] == "assigned"
