"""Concurrent launches bind by attestation across every launchable harness."""

from runtime.api.domain.session_launch_attested_binding_test_support import (
    bind as bind,
    registered_launch as registered_launch,
)


from uuid import uuid4

import pytest

from yoke_contracts.session_control.capabilities import SESSION_SURFACE_CAPABILITIES
from yoke_core.domain.session_launch_execution import (
    report_launch_attempt,
)
from yoke_core.domain.session_launch_registration import (
    complete_launch_for_message,
    complete_launch_injection,
    prepare_launch_registration,
)
from yoke_core.domain.session_launch_registration_candidate import (
    reserve_launch_registration_candidate,
)
from yoke_core.domain.session_launch_store import get_launch
from yoke_core.domain.session_launch_types import SessionLaunchError
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    relay_connection,
)


LAUNCH_SURFACES = [
    surface
    for surface, capability in SESSION_SURFACE_CAPABILITIES.items()
    if capability.create == "supported"
]


@pytest.mark.parametrize("surface", LAUNCH_SURFACES)
def test_overlapping_launches_bind_their_own_authenticated_sessions(surface):
    conn = relay_connection()
    add_relay(
        conn,
        surface=surface,
        version=SESSION_SURFACE_CAPABILITIES[surface].minimum_version,
    )
    first, first_claim, first_session = registered_launch(conn, surface, "first")
    second, second_claim, second_session = registered_launch(conn, surface, "second")
    # Same machine, directory and start instant; reverse hook arrival order.
    bind(conn, second, second_claim, second_session)
    bind(conn, first, first_claim, first_session)
    assert get_launch(conn, first.launch_id).registered_session_id == first_session
    assert get_launch(conn, second.launch_id).registered_session_id == second_session
    for launch, claim, session in (
        (first, first_claim, first_session),
        (second, second_claim, second_session),
    ):
        assert reserve_launch_registration_candidate(
            conn,
            launch_id=launch.launch_id,
            lease_id=claim.lease_id,
            now="2026-08-22T12:00:03Z",
        ) == {"status": "registration_bound", "session_id": session}
        assert (
            conn.execute(
                "SELECT launch_origin FROM harness_sessions WHERE session_id=?",
                (session,),
            ).fetchone()[0]
            == "yoke"
        )
        recipients = conn.execute(
            "SELECT session_id FROM session_message_recipients WHERE message_id=?",
            (launch.message_id,),
        ).fetchall()
        assert [row[0] for row in recipients] == [session]


@pytest.mark.parametrize("surface", LAUNCH_SURFACES)
def test_native_report_cannot_overwrite_a_hook_delivery_or_acknowledgement(surface):
    conn = relay_connection()
    add_relay(
        conn,
        surface=surface,
        version=SESSION_SURFACE_CAPABILITIES[surface].minimum_version,
    )
    launch, claim, session = registered_launch(conn, surface, "report-after-hook")
    bind(conn, launch, claim, session)
    complete_launch_injection(
        conn, launch_id=launch.launch_id, session_id=session, injected=True, now=NOW
    )
    conn.execute(
        "UPDATE session_message_recipients SET state='acknowledged' WHERE message_id=?",
        (launch.message_id,),
    )
    conn.commit()
    succeeded = complete_launch_for_message(
        conn, message_id=launch.message_id, session_id=session, now=NOW
    )
    reported = report_launch_attempt(
        conn,
        launch_id=launch.launch_id,
        lease_id=claim.lease_id,
        result_code="native_created",
        native_session_id=session,
        now="2026-08-22T12:00:04Z",
    )
    assert reported.registered_session_id == succeeded.registered_session_id
    assert reported.completed_at == succeeded.completed_at
    assert reported.state == "succeeded"
    assert reported.result_code == "registered_and_acknowledged"


@pytest.mark.parametrize("surface", LAUNCH_SURFACES)
def test_wrong_attestation_and_late_wrong_native_report_cannot_steal_binding(surface):
    conn = relay_connection()
    add_relay(
        conn,
        surface=surface,
        version=SESSION_SURFACE_CAPABILITIES[surface].minimum_version,
    )
    launch, claim, session = registered_launch(conn, surface, "refusals")
    with pytest.raises(SessionLaunchError, match="attestation is invalid"):
        prepare_launch_registration(
            conn,
            launch_id=launch.launch_id,
            attestation="wrong",
            session_id=session,
            now=NOW,
        )
    assert get_launch(conn, launch.launch_id).native_session_id is None
    bind(conn, launch, claim, session)
    with pytest.raises(SessionLaunchError) as refused:
        report_launch_attempt(
            conn,
            launch_id=launch.launch_id,
            lease_id=claim.lease_id,
            result_code="native_created",
            native_session_id=str(uuid4()),
            now="2026-08-22T12:00:04Z",
        )
    assert refused.value.code == "native_session_mismatch"
    assert get_launch(conn, launch.launch_id).registered_session_id == session


def test_unknown_relay_identity_cannot_undo_hook_binding_and_keeps_native_diagnostics():
    conn = relay_connection()
    add_relay(conn)
    launch, claim, session = registered_launch(conn, "codex-cli", "unknown-report")
    bind(conn, launch, claim, session)
    reported = report_launch_attempt(
        conn,
        launch_id=launch.launch_id,
        lease_id=claim.lease_id,
        result_code="outcome_unknown",
        evidence={"native_launch_pid": 4242, "native_launch_phase": "native_running"},
        now="2026-08-22T12:00:04Z",
    )
    assert reported.state == "awaiting_registration"
    assert reported.native_session_id == reported.registered_session_id == session
    assert reported.native_launch_pid == 4242
