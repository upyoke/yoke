"""Terminal settlement of a detached resume the relay already reported running."""

from __future__ import annotations

import json

import pytest

from yoke_contracts.session_control.resume import (
    RESUME_EXITED_NONZERO_RESULT,
    RESUMED_RUNNING_RESULT,
)
from yoke_core.domain.session_relay import claim_relay_job, report_relay_job
from yoke_core.domain.session_relay_types import SessionRelayError
from runtime.api.domain.test_session_relay import (
    RELAY_ID,
    _add_wake_recipient,
    _clock,
    _connection,
    _heartbeat,
)


SPAWNED_AT = "2026-08-22T12:00:05Z"
# Long past the batch horizon the spawn was leased under: a resumed turn runs
# for minutes, which is the whole reason its outcome arrives on a later poll.
SETTLED_AT = "2026-08-22T12:40:00Z"


def _spawned(conn):
    claimed = claim_relay_job(conn, _heartbeat(), wait_seconds=0, now_provider=_clock())
    job = claimed.jobs[0]
    report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="wake",
        job_id=job.job_id,
        lease_id=job.lease_id,
        result_code=RESUMED_RUNNING_RESULT,
        adapter_revision="claude-native-v3",
        evidence={"native_pid": 96192},
        now=SPAWNED_AT,
    )
    return job


def _attempt(conn, attempt_id: str):
    return conn.execute(
        "SELECT completed_at,result_code,adapter_revision,evidence "
        "FROM session_message_attempts WHERE attempt_id=?",
        (attempt_id,),
    ).fetchone()


def test_a_running_resume_settles_after_its_batch_drained() -> None:
    conn = _connection()
    _add_wake_recipient(conn)
    job = _spawned(conn)
    assert _attempt(conn, job.job_id)[0] is None

    settled = report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="wake",
        job_id=job.job_id,
        lease_id=job.lease_id,
        result_code=RESUME_EXITED_NONZERO_RESULT,
        adapter_revision=None,
        evidence={"exit_code": 3, "native_error_step": "resume"},
        now=SETTLED_AT,
    )

    assert settled["result_code"] == RESUME_EXITED_NONZERO_RESULT
    completed_at, result_code, adapter_revision, evidence = _attempt(conn, job.job_id)
    assert completed_at == SETTLED_AT
    assert result_code == RESUME_EXITED_NONZERO_RESULT
    # A settlement report names no adapter; the spawn's revision must survive.
    assert adapter_revision == "claude-native-v3"
    stored = json.loads(evidence)
    assert stored["exit_code"] == 3
    assert stored["native_error_step"] == "resume"
    assert stored["native_pid"] == 96192


def test_a_settled_resume_refuses_a_second_conflicting_outcome() -> None:
    conn = _connection()
    _add_wake_recipient(conn)
    job = _spawned(conn)
    report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="wake",
        job_id=job.job_id,
        lease_id=job.lease_id,
        result_code=RESUME_EXITED_NONZERO_RESULT,
        adapter_revision=None,
        evidence={"exit_code": 3},
        now=SETTLED_AT,
    )

    repeated = report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="wake",
        job_id=job.job_id,
        lease_id=job.lease_id,
        result_code=RESUME_EXITED_NONZERO_RESULT,
        adapter_revision=None,
        evidence={"exit_code": 3},
        now="2026-08-22T12:41:00Z",
    )
    with pytest.raises(SessionRelayError) as conflict:
        report_relay_job(
            conn,
            actor_id=1,
            relay_id=RELAY_ID,
            job_kind="wake",
            job_id=job.job_id,
            lease_id=job.lease_id,
            result_code="accepted",
            adapter_revision=None,
            now="2026-08-22T12:42:00Z",
        )

    assert repeated["result_code"] == RESUME_EXITED_NONZERO_RESULT
    assert conflict.value.code == "report_conflict"


def test_a_settlement_still_needs_the_lease_the_attempt_was_started_under() -> None:
    conn = _connection()
    _add_wake_recipient(conn)
    job = _spawned(conn)

    with pytest.raises(SessionRelayError) as mismatch:
        report_relay_job(
            conn,
            actor_id=1,
            relay_id=RELAY_ID,
            job_kind="wake",
            job_id=job.job_id,
            lease_id="a-lease-this-relay-never-held",
            result_code=RESUME_EXITED_NONZERO_RESULT,
            adapter_revision=None,
            now=SETTLED_AT,
        )

    assert mismatch.value.code == "lease_mismatch"
    assert _attempt(conn, job.job_id)[1] == RESUMED_RUNNING_RESULT
