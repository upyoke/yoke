"""A wake handed back because every relay worker is busy keeps its budget.

The relay claims on every poll, including while its workers are full. A wake
it cannot start comes back as ``released`` with ``relay_workers_busy``. That
hand-back must not spend one of the receipt's ``max_wake_attempts``: the next
claim takes the same wake again with its count where it was (YOK-5294).
"""

from __future__ import annotations

from runtime.api.domain.session_relay_test_support import (
    RELAY_ID,
    _add_wake_recipient,
    _clock,
    _connection,
    _heartbeat,
)
from yoke_core.domain.session_relay import claim_relay_job, report_relay_job


CLAIMED_AT = "2026-08-22T12:00:00Z"
RELEASED_AT = "2026-08-22T12:00:01Z"
RECLAIMED_AT = "2026-08-22T12:00:02Z"


def _claim(conn, now: str):
    return claim_relay_job(conn, _heartbeat(), wait_seconds=0, now_provider=_clock(now))


def _attempt_count(conn) -> int:
    return conn.execute(
        "SELECT wake_attempt_count FROM session_message_recipients "
        "WHERE message_id='message-1' AND session_id='target'"
    ).fetchone()[0]


def test_busy_hand_back_restores_the_wake_attempt_and_reclaims() -> None:
    conn = _connection()
    _add_wake_recipient(conn)
    before = _attempt_count(conn)
    first = _claim(conn, CLAIMED_AT).jobs
    assert [job.job_kind for job in first] == ["wake"]
    assert _attempt_count(conn) == before + 1

    report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="wake",
        job_id=first[0].job_id,
        lease_id=first[0].lease_id,
        result_code="released",
        evidence={"result_code": "relay_workers_busy"},
        now=RELEASED_AT,
    )

    assert _attempt_count(conn) == before
    row = conn.execute(
        "SELECT completed_at IS NOT NULL,result_code FROM session_message_attempts "
        "WHERE attempt_id=?",
        (first[0].job_id,),
    ).fetchone()
    assert tuple(row) == (1, "released")

    again = _claim(conn, RECLAIMED_AT).jobs
    assert [job.job_kind for job in again] == ["wake"]
    assert again[0].job_id != first[0].job_id
    assert _attempt_count(conn) == before + 1
