"""Transaction composition for message-driven launch completion."""

import json

import pytest

from yoke_core.domain.session_launch_execution import (
    claim_assigned_launch,
    report_launch_attempt,
)
from yoke_core.domain.session_launch_registration import (
    complete_launch_for_message,
    complete_launch_injection,
    prepare_launch_registration,
)
from yoke_core.domain.session_launch_store import get_launch
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    launch_connection,
)


def test_message_completion_can_share_the_callers_transaction() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch = assigned_launch(conn, key="shared-transaction")
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
        native_session_id="session-shared-transaction",
        now="2026-08-22T12:00:30Z",
    )
    conn.execute(
        "INSERT INTO harness_sessions VALUES "
        "('session-shared-transaction', 10, 'codex-cli', '0.148.0a15', "
        "'machine-1', 'gpt-5')"
    )
    conn.commit()
    prepare_launch_registration(
        conn,
        launch_id=launch.launch_id,
        attestation=claim.attestation,
        session_id="session-shared-transaction",
        now="2026-08-22T12:00:31Z",
    )
    conn.execute(
        "UPDATE session_message_recipients SET state='injected' "
        "WHERE message_id=?",
        (launch.message_id,),
    )
    completed = complete_launch_for_message(
        conn,
        message_id=launch.message_id,
        session_id="session-shared-transaction",
        now="2026-08-22T12:00:32Z",
        commit=False,
    )
    assert completed and completed.state == "succeeded"
    conn.rollback()
    assert get_launch(conn, launch.launch_id).state == "awaiting_registration"


@pytest.mark.parametrize(
    ("injected", "expected_result"),
    ((True, "injected"), (False, "render_output_missing")),
)
def test_first_launch_instruction_records_append_only_attempt_evidence(
    injected: bool,
    expected_result: str,
) -> None:
    conn = launch_connection()
    add_relay(conn)
    launch = assigned_launch(conn, key="first-instruction-evidence")
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
        native_session_id="session-first-instruction-evidence",
        now="2026-08-22T12:00:30Z",
    )
    conn.execute(
        "INSERT INTO harness_sessions VALUES "
        "('session-first-instruction-evidence', 10, 'codex-cli', '0.148.0a15', "
        "'machine-1', 'gpt-5')"
    )
    conn.commit()
    prepare_launch_registration(
        conn,
        launch_id=launch.launch_id,
        attestation=claim.attestation,
        session_id="session-first-instruction-evidence",
        now="2026-08-22T12:00:31Z",
    )

    complete_launch_injection(
        conn,
        launch_id=launch.launch_id,
        session_id="session-first-instruction-evidence",
        injected=injected,
        now="2026-08-22T12:00:32Z",
    )

    attempt = conn.execute(
        "SELECT attempt_kind,adapter_revision,started_at,completed_at,"
        "result_code,evidence FROM session_message_attempts WHERE message_id=?",
        (launch.message_id,),
    ).fetchone()
    assert tuple(attempt[:5]) == (
        "hook",
        "session-launch-attestation-v1",
        "2026-08-22T12:00:32Z",
        "2026-08-22T12:00:32Z",
        expected_result,
    )
    assert json.loads(attempt[5]) == {"delivery_path": "launch_attestation"}
    assert "Inspect the current work" not in attempt[5]
