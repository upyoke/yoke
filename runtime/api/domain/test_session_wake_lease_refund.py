"""An explicit wake the relay never reported on is retried, within a bound."""

from __future__ import annotations

import json

import pytest
from datetime import timedelta

from yoke_contracts.session_control.wake_delivery import (
    NATIVE_RESUME_ACCEPTED_RESULT,
)
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.session_broker_wake_fallback import BROKER_JOB_TIMEOUT_SECONDS
from yoke_core.domain.session_broker_wake_settlement import (
    complete_broker_hook_lease,
    settle_broker_wake_losses,
)
from runtime.api.domain import session_broker_test_support as broker
from yoke_core.domain.session_relay import claim_relay_job, report_relay_job
from yoke_core.domain.session_relay_types import WAKE_LEASE_SECONDS
from yoke_core.domain.session_wake_lease_refund import (
    LEASE_EXPIRED_RESULT,
    MAX_REFUNDED_LEASE_EXPIRIES,
    refund_unreported_wake,
)
from runtime.api.domain.test_session_relay import (
    RELAY_ID,
    _add_wake_recipient,
    _clock,
    _connection,
    _heartbeat,
)


CLAIMED_AT = "2026-08-22T11:30:00Z"


def _later(seconds: int) -> str:
    instant = parse_instant(CLAIMED_AT) + timedelta(seconds=seconds)
    return instant.strftime("%Y-%m-%dT%H:%M:%SZ")


def _explicit_recipient():
    conn = _connection()
    _add_wake_recipient(conn)
    conn.execute(
        "UPDATE session_message_recipients SET routing_snapshot=? "
        "WHERE message_id='message-1'",
        (json.dumps({"explicit_stopped_wake": True}),),
    )
    conn.commit()
    return conn


def _claim(conn, now: str):
    return claim_relay_job(conn, _heartbeat(), wait_seconds=0, now_provider=_clock(now))


def _recipient(conn) -> tuple[int, str | None]:
    return tuple(
        conn.execute(
            "SELECT wake_attempt_count,wake_escalation FROM session_message_recipients "
            "WHERE message_id='message-1'"
        ).fetchone()
    )


def _wake_results(conn) -> list[str | None]:
    return [
        row[0]
        for row in conn.execute(
            "SELECT result_code FROM session_message_attempts "
            "WHERE attempt_kind='wake_relay' ORDER BY started_at,attempt_id"
        ).fetchall()
    ]


#: One retry cycle: a poll past the lease settles the expiry, and the direct
#: route then leaves the receipt to the peer-hook broker for a broker job's
#: timeout before it claims again.
_CYCLE = WAKE_LEASE_SECONDS + 1 + BROKER_JOB_TIMEOUT_SECONDS + 1


def _retry_cycle(conn, cycle: int):
    """Settle the open attempt's expiry, then poll once the broker window ends."""
    start = _CYCLE * (cycle - 1)
    settled = _claim(conn, _later(start + WAKE_LEASE_SECONDS + 1))
    assert not settled.jobs, "the direct route waits for the broker first"
    return _claim(conn, _later(start + _CYCLE))


def test_an_explicit_wake_that_expired_unreported_is_claimed_again() -> None:
    conn = _explicit_recipient()
    assert _claim(conn, CLAIMED_AT).jobs
    assert _recipient(conn) == (1, None)

    retried = _retry_cycle(conn, 1)

    assert _wake_results(conn) == [LEASE_EXPIRED_RESULT, None]
    assert len(retried.jobs) == 1
    assert _recipient(conn) == (1, None)


def test_a_reported_resume_keeps_its_charge_and_is_not_retried() -> None:
    conn = _explicit_recipient()
    job = _claim(conn, CLAIMED_AT).jobs[0]
    report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="wake",
        job_id=job.job_id,
        lease_id=job.lease_id,
        result_code=NATIVE_RESUME_ACCEPTED_RESULT,
        adapter_revision="relay-test-v1",
        evidence={},
        now=_later(5),
    )

    retried = _retry_cycle(conn, 1)

    assert not retried.jobs
    assert LEASE_EXPIRED_RESULT not in _wake_results(conn)
    assert _recipient(conn) == (1, None)


def test_a_delivered_envelope_is_not_retried_after_expiry() -> None:
    conn = _explicit_recipient()
    assert _claim(conn, CLAIMED_AT).jobs
    conn.execute(
        "UPDATE session_message_recipients SET state='acknowledged',"
        "acknowledged_at=? WHERE message_id='message-1'",
        (_later(10),),
    )
    conn.commit()

    retried = _retry_cycle(conn, 1)

    assert not retried.jobs
    assert _wake_results(conn) == [LEASE_EXPIRED_RESULT]
    assert _recipient(conn) == (1, None)


def test_repeated_unreported_expiry_escalates_by_name_after_the_bound() -> None:
    conn = _explicit_recipient()
    assert _claim(conn, CLAIMED_AT).jobs
    for cycle in range(1, MAX_REFUNDED_LEASE_EXPIRIES + 1):
        assert _retry_cycle(conn, cycle).jobs, cycle

    final = _retry_cycle(conn, MAX_REFUNDED_LEASE_EXPIRIES + 1)

    assert not final.jobs
    assert _wake_results(conn) == [LEASE_EXPIRED_RESULT] * (
        MAX_REFUNDED_LEASE_EXPIRIES + 1
    )
    assert _recipient(conn) == (1, LEASE_EXPIRED_RESULT)


@pytest.mark.parametrize(
    "code", ["broker_hook_lease_expired", "broker_lost", "broker_timeout"]
)
def test_broker_loss_refunds_budget_and_recovered_relay_wakes(code: str) -> None:
    conn, message_id = broker._seed()
    lease = broker._reserve(conn)
    assert lease
    if code != "broker_hook_lease_expired":
        complete_broker_hook_lease(
            conn,
            lease_id=lease.lease_id,
            delivered=True,
            result="injected",
            now=broker.NOW + timedelta(seconds=2),
        )
    if code == "broker_lost":
        conn.execute(
            "UPDATE harness_sessions SET turn_posture='waiting' "
            "WHERE session_id='broker-a'"
        )
        conn.commit()
    recovered_at = broker.NOW + timedelta(seconds=BROKER_JOB_TIMEOUT_SECONDS + 2)

    assert settle_broker_wake_losses(conn, now=recovered_at) == 1
    assert tuple(
        conn.execute(
            "SELECT result_code,completed_at IS NOT NULL "
            "FROM session_message_attempts WHERE attempt_id=?",
            (lease.attempt_id,),
        ).fetchone()
    ) == (code, 1)
    assert tuple(
        conn.execute(
            "SELECT wake_attempt_count,wake_escalation FROM session_message_recipients "
            "WHERE message_id=?",
            (message_id,),
        ).fetchone()
    ) == (0, None)
    assert settle_broker_wake_losses(conn, now=recovered_at) == 0
    recovered = claim_relay_job(
        conn,
        broker._heartbeat(),
        wait_seconds=0,
        now_provider=lambda: broker._stamp(seconds=BROKER_JOB_TIMEOUT_SECONDS + 3),
    )
    assert len(recovered.jobs) == 1
    assert recovered.jobs[0].message_id == message_id


@pytest.mark.parametrize(
    "final_kind,final_code",
    [
        ("wake_relay", LEASE_EXPIRED_RESULT),
        ("wake_broker", "broker_timeout"),
    ],
)
def test_mixed_unreported_losses_share_refund_limit(final_kind, final_code) -> None:
    conn = _explicit_recipient()
    for index in range(MAX_REFUNDED_LEASE_EXPIRIES + 1):
        kind, code = (
            (final_kind, final_code)
            if index == MAX_REFUNDED_LEASE_EXPIRIES
            else ("wake_broker", "broker_lost")
            if index % 2
            else ("wake_relay", LEASE_EXPIRED_RESULT)
        )
        attempt_id = f"unreported-{index}"
        conn.execute(
            "UPDATE session_message_recipients "
            "SET wake_attempt_count=wake_attempt_count+1"
        )
        conn.execute(
            "INSERT INTO session_message_attempts "
            "(attempt_id,message_id,target_session_id,attempt_kind,started_at,"
            "completed_at,result_code) VALUES (?, 'message-1','target',?,?,?,?)",
            (attempt_id, kind, _later(index), _later(index + 1), code),
        )
        refund_unreported_wake(conn, attempt_id=attempt_id)
        if index < MAX_REFUNDED_LEASE_EXPIRIES:
            assert _recipient(conn) == (0, None)
    assert _recipient(conn) == (1, final_code)


@pytest.mark.parametrize(
    "change,code",
    [
        (
            "UPDATE harness_sessions SET last_tool_call_at=? WHERE session_id='s4'",
            "broker_target_changed",
        ),
        (
            "UPDATE session_message_attempts SET started_at='' WHERE attempt_id=?",
            "broker_state_invalid",
        ),
    ],
)
def test_broker_target_change_and_invalid_state_keep_charge(change, code) -> None:
    conn, _ = broker._seed()
    lease = broker._reserve(conn)
    assert lease
    value = (
        lease.attempt_id if code == "broker_state_invalid" else broker._stamp(seconds=2)
    )
    conn.execute(change, (value,))
    conn.commit()
    assert (
        settle_broker_wake_losses(
            conn, now=broker.NOW + timedelta(seconds=BROKER_JOB_TIMEOUT_SECONDS + 2)
        )
        == 1
    )
    assert (
        conn.execute(
            "SELECT result_code FROM session_message_attempts WHERE attempt_id=?",
            (lease.attempt_id,),
        ).fetchone()[0]
        == code
    )
    assert (
        conn.execute(
            "SELECT wake_attempt_count FROM session_message_recipients"
        ).fetchone()[0]
        == 1
    )
