"""Complete receipt contracts for every wake-attempt settlement boundary."""

from __future__ import annotations

import pytest

from runtime.api.domain.test_session_relay import (
    RELAY_ID,
    _add_wake_recipient,
    _clock,
    _connection,
    _heartbeat,
)
from yoke_contracts.session_control.resume import RESUMED_RUNNING_RESULT
from yoke_contracts.session_control.wake_delivery import (
    NATIVE_RESUME_ACCEPTED_RESULT,
    WAKE_DELIVERY_UNVERIFIED_RESULTS,
    WAKE_REPORT_CODES,
)
from yoke_core.domain.session_broker_wake import BROKER_ADAPTER_REVISION
from yoke_core.domain.session_broker_wake_settlement import close_broker_attempt
from yoke_core.domain.session_message_attempt_reads import message_attempt_evidence
from yoke_core.domain.session_relay import claim_relay_job, report_relay_job
from yoke_core.domain.session_relay_expiry import (
    RELAY_EXPIRY_ADAPTER_REVISION,
    settle_expired_relay_leases,
)
from yoke_core.domain.session_wake_reconciliation import (
    WAKE_RECONCILIATION_ADAPTER_REVISION,
    reconcile_spawned_wake_attempts,
)


NATIVE_ADAPTER_REVISION = "test-native-wake-v1"
STARTED_AT = "2026-08-22T12:00:00Z"
# Every reported code that closes its attempt on the spot. The rest name a
# native the relay started and leave delivery for the receipt to settle.
TERMINAL_RELAY_RESULTS = tuple(
    sorted(WAKE_REPORT_CODES - WAKE_DELIVERY_UNVERIFIED_RESULTS)
)


def _claim_direct_wake(conn, *, now: str = STARTED_AT):
    claimed = claim_relay_job(
        conn,
        _heartbeat(),
        wait_seconds=0,
        now_provider=_clock(now),
    )
    assert len(claimed.jobs) == 1
    return claimed.jobs[0]


def _report(conn, job, result_code: str, *, adapter_revision: str | None) -> None:
    report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="wake",
        job_id=job.job_id,
        lease_id=job.lease_id,
        result_code=result_code,
        adapter_revision=adapter_revision,
        now="2026-08-22T12:00:10Z",
    )


def _attempt_row(conn, attempt_id: str):
    return conn.execute(
        "SELECT attempt_id,started_at,completed_at,result_code,adapter_revision "
        "FROM session_message_attempts WHERE attempt_id=?",
        (attempt_id,),
    ).fetchone()


@pytest.mark.parametrize("result_code", TERMINAL_RELAY_RESULTS)
def test_each_relay_terminal_result_writes_a_complete_receipt(
    result_code: str,
) -> None:
    conn = _connection()
    _add_wake_recipient(conn)
    job = _claim_direct_wake(conn)

    _report(conn, job, result_code, adapter_revision=NATIVE_ADAPTER_REVISION)

    row = _attempt_row(conn, job.job_id)
    assert tuple(row) == (
        job.job_id,
        STARTED_AT,
        "2026-08-22T12:00:10Z",
        result_code,
        NATIVE_ADAPTER_REVISION,
    )


def test_running_resume_writes_the_complete_in_flight_shape() -> None:
    conn = _connection()
    _add_wake_recipient(conn)
    job = _claim_direct_wake(conn)

    _report(conn, job, RESUMED_RUNNING_RESULT, adapter_revision=NATIVE_ADAPTER_REVISION)

    row = _attempt_row(conn, job.job_id)
    assert tuple(row) == (
        job.job_id,
        STARTED_AT,
        None,
        RESUMED_RUNNING_RESULT,
        NATIVE_ADAPTER_REVISION,
    )


def test_relay_report_writer_supplies_a_revision_when_native_report_did_not() -> None:
    conn = _connection()
    _add_wake_recipient(conn)
    job = _claim_direct_wake(conn)

    _report(conn, job, NATIVE_RESUME_ACCEPTED_RESULT, adapter_revision=None)

    row = _attempt_row(conn, job.job_id)
    # In flight until the receipt proves delivery, and already attributable.
    assert row[2] is None
    assert row[3] == NATIVE_RESUME_ACCEPTED_RESULT
    assert row[4]


def test_expired_first_attempt_and_successful_retry_are_both_complete() -> None:
    conn = _connection()
    _add_wake_recipient(conn)
    first = _claim_direct_wake(conn)
    assert settle_expired_relay_leases(conn, now="2026-08-22T12:01:31Z") == 1

    second = _claim_direct_wake(conn, now="2026-08-22T12:06:32Z")
    report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="wake",
        job_id=second.job_id,
        lease_id=second.lease_id,
        result_code=NATIVE_RESUME_ACCEPTED_RESULT,
        adapter_revision=NATIVE_ADAPTER_REVISION,
        now="2026-08-22T12:06:40Z",
    )
    # The retry is complete once its envelope lands, not once it is reported.
    conn.execute(
        "UPDATE session_message_recipients SET state='injected',"
        "injection_count=1,last_injected_at=? WHERE message_id='message-1'",
        ("2026-08-22T12:07:00Z",),
    )
    conn.commit()
    assert reconcile_spawned_wake_attempts(conn, now="2026-08-22T12:07:10Z") == 1

    receipts = message_attempt_evidence(conn, "message-1")
    assert receipts["attempt_count"] == 2
    assert [attempt["attempt_id"] for attempt in receipts["attempts"]] == [
        first.job_id,
        second.job_id,
    ]
    assert [attempt["adapter_revision"] for attempt in receipts["attempts"]] == [
        RELAY_EXPIRY_ADAPTER_REVISION,
        NATIVE_ADAPTER_REVISION,
    ]
    assert all(attempt["completed_at"] for attempt in receipts["attempts"])


def test_broker_loss_writer_supplies_its_revision() -> None:
    conn = _connection()
    _add_wake_recipient(conn)
    conn.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id,message_id,target_session_id,attempt_kind,lease_id,started_at,"
        "result_code,evidence) VALUES (?,?,?,?,?,?,?,?)",
        (
            "broker-attempt",
            "message-1",
            "target",
            "wake_broker",
            "broker-lease",
            STARTED_AT,
            "broker_hook_leased",
            "{}",
        ),
    )

    assert close_broker_attempt(
        conn,
        attempt_id="broker-attempt",
        result_code="broker_hook_lease_expired",
        now="2026-08-22T12:00:31Z",
    )

    row = _attempt_row(conn, "broker-attempt")
    assert tuple(row[2:]) == (
        "2026-08-22T12:00:31Z",
        "broker_hook_lease_expired",
        BROKER_ADAPTER_REVISION,
    )


def test_reconciliation_writer_supplies_a_revision_when_native_report_did_not() -> None:
    conn = _connection()
    _add_wake_recipient(conn)
    conn.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id,message_id,target_session_id,attempt_kind,started_at,"
        "result_code,evidence) VALUES (?,?,?,?,?,?,?)",
        (
            "resume-attempt",
            "message-1",
            "target",
            "wake_relay",
            STARTED_AT,
            RESUMED_RUNNING_RESULT,
            "{}",
        ),
    )
    conn.commit()

    assert reconcile_spawned_wake_attempts(conn, now="2026-08-22T12:20:01Z") == 1

    row = _attempt_row(conn, "resume-attempt")
    assert row[2]
    assert row[3] == "resume_never_started"
    assert row[4] == WAKE_RECONCILIATION_ADAPTER_REVISION
