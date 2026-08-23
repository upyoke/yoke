"""Claude background-session launch registration tests."""

from __future__ import annotations

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


def test_attestation_binds_the_actual_background_session() -> None:
    conn = launch_connection()
    add_relay(conn, surface="claude-cli", version="2.1.238")
    launch = assigned_launch(
        conn,
        key="claude-background",
        surface="claude-cli",
    )
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
        native_session_id="provisional-launch-session",
        adapter_revision="claude-native-v1",
        evidence={"duration_ms": 40, "exit_code": 0},
        now="2026-08-22T12:00:30Z",
    )
    actual_session_id = "claude-allocated-session"
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, project_id, executor_surface, executor_version, machine_id, model) "
        "VALUES (?, 10, 'claude-cli', '2.1.238', 'machine-1', 'gpt-5')",
        (actual_session_id,),
    )
    conn.commit()

    injection = prepare_launch_registration(
        conn,
        launch_id=launch.launch_id,
        attestation=claim.attestation,
        session_id=actual_session_id,
        now="2026-08-22T12:00:31Z",
    )

    bound = get_launch(conn, launch.launch_id)
    assert injection.session_id == actual_session_id
    assert bound.native_session_id == actual_session_id
    assert bound.registered_session_id == actual_session_id
    assert bound.attestation_consumed_at == "2026-08-22T12:00:31Z"
