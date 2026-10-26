"""Cancellation behavior for in-progress native session creation."""

import pytest

from yoke_core.domain.session_launch_cancellation import (
    SESSION_WORKING_CODE,
    cancel_launch,
)
from yoke_core.domain.session_launch_execution import claim_assigned_launch
from yoke_core.domain.session_launch_store import get_launch, update_launch
from yoke_core.domain.session_launch_types import SessionLaunchError
from yoke_core.domain.sessions_analytics import SessionError
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    authorization,
    launch_connection,
)

TERMINATE = (
    "yoke_core.domain.session_launch_cancellation.terminate_cancelled_launch_session"
)


def _launch_bound_to(conn, *, key: str, state: str, result_code: str):
    add_relay(conn)
    launch = assigned_launch(conn, key=key)
    conn.execute(
        "INSERT INTO harness_sessions (session_id, project_id) VALUES ('worker', 10)"
    )
    update_launch(
        conn,
        launch.launch_id,
        state=state,
        result_code=result_code,
        native_session_id="worker",
        registered_session_id="worker",
    )
    conn.commit()
    return launch


def test_cancelling_during_native_create_preserves_unknown_outcome() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch = assigned_launch(conn, key="cancel-launching")
    claim_assigned_launch(
        conn,
        launch_id=launch.launch_id,
        relay_id="relay-1",
        machine_id="machine-1",
        now=NOW,
    )

    result = cancel_launch(
        conn,
        launch_id=launch.launch_id,
        auth=authorization(),
        now=NOW,
    )

    assert result.state == "outcome_unknown"
    assert result.result_code == "cancellation_requires_reconciliation"


def test_cancel_ends_a_registered_session_that_has_not_received_work(
    monkeypatch,
) -> None:
    ended: list[dict] = []
    monkeypatch.setattr(TERMINATE, lambda conn, **kwargs: ended.append(kwargs))
    conn = launch_connection()
    launch = _launch_bound_to(
        conn,
        key="cancel-unworked",
        state="awaiting_registration",
        result_code="injected_awaiting_acknowledgement",
    )

    result = cancel_launch(
        conn, launch_id=launch.launch_id, auth=authorization(), now=NOW
    )

    assert result.state == "cancelled"
    assert result.result_code == "cancelled_session_ended"
    assert [call["target_session_id"] for call in ended] == ["worker"]
    assert ended[0]["actor_id"] == 1


def test_cancel_refuses_a_session_already_working(
    monkeypatch,
) -> None:
    monkeypatch.setattr(TERMINATE, lambda conn, **kwargs: pytest.fail("ended"))
    conn = launch_connection()
    launch = _launch_bound_to(
        conn, key="cancel-working", state="succeeded", result_code="registered"
    )

    with pytest.raises(SessionLaunchError) as refused:
        cancel_launch(conn, launch_id=launch.launch_id, auth=authorization(), now=NOW)

    assert refused.value.code == SESSION_WORKING_CODE
    assert get_launch(conn, launch.launch_id).state == "succeeded"


@pytest.mark.parametrize("end_column", ["ended_at", "terminated_at"])
def test_cancel_settles_a_delivered_launch_whose_registered_session_ended(
    monkeypatch, end_column
) -> None:
    monkeypatch.setattr(TERMINATE, lambda conn, **kwargs: pytest.fail("ended again"))
    conn = launch_connection()
    launch = _launch_bound_to(
        conn,
        key="cancel-ended",
        state="awaiting_registration",
        result_code="launch_work_claim_pending",
    )
    conn.execute(
        f"UPDATE harness_sessions SET {end_column} = ? WHERE session_id = ?",
        (NOW, "worker"),
    )
    conn.commit()

    result = cancel_launch(
        conn, launch_id=launch.launch_id, auth=authorization(), now=NOW
    )

    assert result.state == "cancelled"
    assert result.result_code == "cancelled_session_ended"
    assert result.completed_at is not None


def test_refused_session_ending_leaves_the_launch_uncancelled(monkeypatch) -> None:
    def refuse(conn, **kwargs):
        raise SessionError("TERMINATION_RESUME_IN_FLIGHT", "worker is resuming")

    monkeypatch.setattr(TERMINATE, refuse)
    conn = launch_connection()
    launch = _launch_bound_to(
        conn,
        key="cancel-refused",
        state="awaiting_registration",
        result_code="injected_awaiting_acknowledgement",
    )

    with pytest.raises(SessionLaunchError) as refused:
        cancel_launch(conn, launch_id=launch.launch_id, auth=authorization(), now=NOW)

    assert refused.value.code == "launch_session_termination_refused"
    assert "TERMINATION_RESUME_IN_FLIGHT" in str(refused.value)
    assert get_launch(conn, launch.launch_id).state == "awaiting_registration"


@pytest.mark.parametrize("exit_code", [0, 1])
def test_cancel_settles_failed_unregistered_native_with_exit_evidence(exit_code):
    conn = launch_connection()
    add_relay(conn)
    launch = assigned_launch(conn, key="cancel-exited")
    evidence = '{"native_exit_at":"2026-08-22T12:00:00Z","exit_code":%d}' % exit_code
    update_launch(
        conn,
        launch.launch_id,
        state="failed",
        result_code="native_exited_unregistered",
        native_session_id="exited-native",
        result_evidence=evidence,
    )
    conn.commit()

    result = cancel_launch(
        conn, launch_id=launch.launch_id, auth=authorization(), now=NOW
    )

    assert result.state == "cancelled"
    assert result.result_code == "cancelled"
    assert result.result_evidence == evidence
    assert (
        cancel_launch(
            conn, launch_id=launch.launch_id, auth=authorization(), now=NOW
        ).state
        == "cancelled"
    )
