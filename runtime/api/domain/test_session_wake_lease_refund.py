"""An explicit wake the relay never reported on is retried, within a bound."""

from __future__ import annotations

import json
from datetime import timedelta

from yoke_contracts.session_control.wake_delivery import (
    NATIVE_RESUME_ACCEPTED_RESULT,
)
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.session_broker_wake_fallback import BROKER_JOB_TIMEOUT_SECONDS
from yoke_core.domain.session_relay import claim_relay_job, report_relay_job
from yoke_core.domain.session_relay_types import WAKE_LEASE_SECONDS
from yoke_core.domain.session_wake_lease_refund import (
    LEASE_EXPIRED_RESULT,
    MAX_REFUNDED_LEASE_EXPIRIES,
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
