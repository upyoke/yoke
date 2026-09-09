"""A wake the relay declined never spends the retry it was charged."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

import json

from yoke_contracts.session_control.wake_delivery import NATIVE_TURN_RUNNING_RESULT
from yoke_harness.session_relay_native_turn_custody import (
    RESUME_CUSTODY_SOURCE,
    RunningNative,
)
from yoke_core.domain.session_relay import claim_relay_job, report_relay_job
from yoke_core.domain.session_relay_types import SessionRelayError
from yoke_core.domain.session_wake_deferral import restore_deferred_wake_budget
from runtime.api.domain.test_session_relay import (
    RELAY_ID,
    _add_wake_recipient,
    _clock,
    _connection,
    _heartbeat,
)


CLAIMED_AT = "2026-08-22T11:30:00Z"
REPORTED_AT = "2026-08-22T11:30:02Z"
#: Built by the producer itself, so a rename on either side of the wire is a
#: failure here rather than a fact that silently stops being stored.
RUNNING_NATIVE = RunningNative(
    session_id="target",
    pid=4001,
    process_start_time="Mon Aug 24 08:00:00 2026",
    source=RESUME_CUSTODY_SOURCE,
)


def _claim_wake(conn, *, now: str = CLAIMED_AT):
    claimed = claim_relay_job(
        conn, _heartbeat(), wait_seconds=0, now_provider=_clock(now)
    )
    assert claimed.jobs, "the seeded recipient should be claimable"
    return claimed.jobs[0]


def _report(
    conn, job, *, result_code: str = NATIVE_TURN_RUNNING_RESULT, now=REPORTED_AT
):
    return report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="wake",
        job_id=job.job_id,
        lease_id=job.lease_id,
        result_code=result_code,
        adapter_revision="relay-custody-v1",
        evidence=dict(RUNNING_NATIVE.evidence),
        now=now,
    )


def _recipient(conn) -> tuple[int, str, str]:
    return conn.execute(
        "SELECT wake_attempt_count,wake_after,state FROM session_message_recipients "
        "WHERE message_id='message-1'"
    ).fetchone()


def test_the_stored_attempt_keeps_the_proof_the_wake_was_refused_on() -> None:
    """The pid, its start time, and the custody family must survive storage.

    Attempt evidence passes through a bounded allowlist that omits every
    field it does not know, so a fact the relay reports is not a fact an
    operator can read. These three are the whole proof that a wake was
    declined against a specific live process rather than for no reason, and
    a reader on another machine has nothing else to check it with.
    """
    conn = _connection()
    _add_wake_recipient(conn)
    job = _claim_wake(conn)

    _report(conn, job)

    stored = json.loads(
        conn.execute(
            "SELECT evidence FROM session_message_attempts WHERE attempt_id=?",
            (job.job_id,),
        ).fetchone()[0]
    )
    assert stored["running_native_pid"] == RUNNING_NATIVE.pid
    assert stored["running_native_start_time"] == RUNNING_NATIVE.process_start_time
    assert stored["running_native_source"] == RUNNING_NATIVE.source
    assert stored["result_code"] == NATIVE_TURN_RUNNING_RESULT


def test_an_unknown_evidence_field_is_still_dropped() -> None:
    """Widening the allowlist must not widen it to everything."""
    conn = _connection()
    _add_wake_recipient(conn)
    job = _claim_wake(conn)

    report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="wake",
        job_id=job.job_id,
        lease_id=job.lease_id,
        result_code=NATIVE_TURN_RUNNING_RESULT,
        adapter_revision="relay-custody-v1",
        evidence={**RUNNING_NATIVE.evidence, "native_environment_dump": "SECRET=1"},
        now=REPORTED_AT,
    )

    stored = json.loads(
        conn.execute(
            "SELECT evidence FROM session_message_attempts WHERE attempt_id=?",
            (job.job_id,),
        ).fetchone()[0]
    )
    assert "native_environment_dump" not in stored
    assert stored["running_native_pid"] == RUNNING_NATIVE.pid


def test_a_deferred_wake_gives_its_attempt_back() -> None:
    conn = _connection()
    _add_wake_recipient(conn)
    job = _claim_wake(conn)
    charged, _wake_after, _state = _recipient(conn)
    assert charged == 1

    _report(conn, job)

    count, wake_after, state = _recipient(conn)
    assert count == 0
    # Still pending: hook delivery is untouched, so the envelope is waiting
    # for the running turn's own next hook.
    assert state == "pending"
    assert wake_after > REPORTED_AT


def test_a_delivered_wake_still_spends_its_attempt() -> None:
    conn = _connection()
    _add_wake_recipient(conn)
    job = _claim_wake(conn)

    _report(conn, job, result_code="resumed_running")

    assert _recipient(conn)[0] == 1


def test_a_repeated_deferral_report_refunds_once() -> None:
    conn = _connection()
    _add_wake_recipient(conn)
    job = _claim_wake(conn)

    _report(conn, job)
    again = _report(conn, job, now="2026-08-22T11:30:05Z")

    assert again["result_code"] == NATIVE_TURN_RUNNING_RESULT
    assert _recipient(conn)[0] == 0


def test_a_conflicting_second_report_is_still_refused() -> None:
    conn = _connection()
    _add_wake_recipient(conn)
    job = _claim_wake(conn)
    _report(conn, job)

    with pytest.raises(SessionRelayError) as refusal:
        _report(conn, job, result_code="failed", now="2026-08-22T11:30:06Z")

    assert refusal.value.code == "report_conflict"


def test_concurrent_duplicate_reports_refund_once(tmp_path) -> None:
    """Two copies of one report must not give the same attempt back twice.

    The read that establishes the attempt is open cannot serialize them on
    its own; the settling write is what does, so exactly one copy reaches
    the refund.
    """
    path = tmp_path / "wake-deferral.sqlite"
    seed = _connection_at(path)
    _add_wake_recipient(seed)
    job = _claim_wake(seed)
    seed.close()

    def report_once() -> str:
        conn = sqlite3.connect(path, timeout=5, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            return str(_report(conn, job)["result_code"])
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: report_once(), range(2)))

    assert results == [NATIVE_TURN_RUNNING_RESULT, NATIVE_TURN_RUNNING_RESULT]
    check = sqlite3.connect(path)
    count = check.execute(
        "SELECT wake_attempt_count FROM session_message_recipients "
        "WHERE message_id='message-1'"
    ).fetchone()[0]
    check.close()
    assert count == 0


def test_duplicate_settled_before_batch_check_is_accepted(monkeypatch) -> None:
    """The winner may clear the relay batch before the duplicate checks it."""
    from yoke_core.domain import session_relay_jobs

    conn = _connection()
    _add_wake_recipient(conn)
    job = _claim_wake(conn)
    original = session_relay_jobs.require_relay_batch

    def settle_and_clear(inner_conn, *, relay_id: str, now: str) -> None:
        inner_conn.execute(
            "UPDATE session_message_attempts SET completed_at=?,result_code=? "
            "WHERE attempt_id=?",
            (now, NATIVE_TURN_RUNNING_RESULT, job.job_id),
        )
        inner_conn.execute(
            "UPDATE session_relays SET lease_id=NULL,lease_expires_at=NULL "
            "WHERE relay_id=?",
            (relay_id,),
        )
        original(inner_conn, relay_id=relay_id, now=now)

    monkeypatch.setattr(
        session_relay_jobs, "require_relay_batch", settle_and_clear,
    )

    answered = _report(conn, job)

    assert answered["result_code"] == NATIVE_TURN_RUNNING_RESULT
    assert _recipient(conn)[0] == 1


def _settle_between_read_and_write(conn, *, result_code: str, monkeypatch) -> None:
    """Make another copy of the report win the settling write.

    The race this guards is narrow — both copies read the attempt open, then
    one writes first — so it is produced deterministically rather than waited
    for, by settling the row from inside the batch check the reporting path
    already runs between its own read and its own write.
    """
    from yoke_core.domain import session_relay_jobs

    original = session_relay_jobs.require_relay_batch

    def settle_first(inner_conn, *, relay_id: str, now: str) -> None:
        inner_conn.execute(
            "UPDATE session_message_attempts SET completed_at=?,result_code=? "
            "WHERE completed_at IS NULL",
            (now, result_code),
        )
        original(inner_conn, relay_id=relay_id, now=now)

    monkeypatch.setattr(session_relay_jobs, "require_relay_batch", settle_first)


def test_a_report_that_loses_the_settling_write_refunds_nothing(monkeypatch) -> None:
    conn = _connection()
    _add_wake_recipient(conn)
    job = _claim_wake(conn)
    _settle_between_read_and_write(
        conn, result_code=NATIVE_TURN_RUNNING_RESULT, monkeypatch=monkeypatch
    )

    answered = _report(conn, job)

    assert answered["result_code"] == NATIVE_TURN_RUNNING_RESULT
    # The winner owns the refund; this copy must not take the attempt back
    # a second time.
    assert _recipient(conn)[0] == 1


def test_a_report_that_loses_to_a_different_outcome_is_refused(monkeypatch) -> None:
    conn = _connection()
    _add_wake_recipient(conn)
    job = _claim_wake(conn)
    _settle_between_read_and_write(conn, result_code="failed", monkeypatch=monkeypatch)

    with pytest.raises(SessionRelayError) as refusal:
        _report(conn, job)

    assert refusal.value.code == "report_conflict"


def test_a_late_deferral_leaves_a_newer_attempt_alone() -> None:
    """A newer claim owns the budget and the backoff; a late refund yields.

    The settling write already stops a duplicate from reaching the refund
    sequentially. This asserts the refund itself declines while another wake
    attempt is open, which is what a concurrent interleave would produce.
    """
    conn = _connection()
    _add_wake_recipient(conn)
    _claim_wake(conn)
    before = _recipient(conn)

    restore_deferred_wake_budget(
        conn,
        message_id="message-1",
        session_id="target",
        now=REPORTED_AT,
    )

    assert _recipient(conn) == before


def _connection_at(path) -> sqlite3.Connection:
    """Re-seed the shared relay fixture into a file the threads can share."""
    from runtime.api.domain.session_launch_test_support import relay_connection

    memory = relay_connection()
    disk = sqlite3.connect(path, timeout=5, check_same_thread=False)
    memory.backup(disk)
    memory.close()
    disk.row_factory = sqlite3.Row
    return disk
