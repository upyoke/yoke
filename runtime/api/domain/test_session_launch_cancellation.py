"""Cancellation behavior for in-progress native session creation."""

from yoke_core.domain.session_launch_execution import claim_assigned_launch
from yoke_core.domain.session_launch_requests import cancel_launch
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    authorization,
    launch_connection,
)


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
