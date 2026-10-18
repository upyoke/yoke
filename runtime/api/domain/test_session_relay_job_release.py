"""Unstarted jobs return to their durable queue under their exact lease."""

from datetime import timedelta
import json

import pytest

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.session_launch_store import get_launch
from yoke_core.domain.session_relay import report_relay_job
from yoke_core.domain.session_relay_types import SessionRelayError
from runtime.api.domain.test_session_relay_independent_jobs import (
    MACHINE_ID,
    NOW,
    RELAY_ID,
    _claim,
    _connection,
    _fetch,
    _wake,
)
from runtime.api.domain.session_launch_test_support import assigned_launch


def _release(conn, job, **overrides):
    args = dict(
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind=job.job_kind,
        job_id=job.job_id,
        lease_id=job.lease_id,
        result_code="released",
        evidence={"result_code": "relay_workers_busy", "recovery": "Retry next claim."},
        now=parse_instant(NOW) + timedelta(seconds=1),
    )
    return report_relay_job(conn, **{**args, **overrides})


def test_launch_release_closes_attempt_and_allows_immediate_reclaim():
    conn = _connection()
    launch = assigned_launch(conn, key="unstarted", machine_id=MACHINE_ID)
    job = _claim(conn)[0]
    _release(conn, job)
    assert _release(conn, job)["result_code"] == "released"
    stored = get_launch(conn, launch.launch_id)
    assert stored.state == "assigned"
    assert stored.attestation_hash is None
    attempt = conn.execute(
        "SELECT completed_at,result_code,evidence FROM session_launch_attempts WHERE lease_id=?",
        (job.lease_id,),
    ).fetchone()
    assert attempt[0] is not None
    assert attempt[1] == "released"
    assert json.loads(attempt[2])["result_code"] == "relay_workers_busy"
    replacement = _claim(conn, 2)[0]
    assert replacement.job_id == job.job_id
    assert replacement.lease_id != job.lease_id
    # A late duplicate cannot release the replacement's lease.
    _release(conn, job)
    assert get_launch(conn, launch.launch_id).state == "launching"


def test_wake_release_refunds_budget_once_and_can_be_reclaimed_immediately():
    conn = _connection()
    _wake(conn, "worker-a", "mail-a")
    job = _claim(conn)[0]
    _release(conn, job)
    _release(conn, job)
    assert (
        conn.execute(
            "SELECT wake_attempt_count FROM session_message_recipients WHERE message_id='mail-a'"
        ).fetchone()[0]
        == 0
    )
    new = _claim(conn, 2)[0]
    assert new.job_kind == "wake"
    assert new.job_id != job.job_id


def test_evidence_release_preserves_request_for_next_claim():
    conn = _connection()
    _wake(conn, "worker-a", "mail-a")
    _fetch(conn, "read-a")
    job = next(j for j in _claim(conn) if j.job_kind == "evidence")
    _release(conn, job)
    _release(conn, job)
    new = next(j for j in _claim(conn, 2) if j.job_kind == "evidence")
    assert new.job_id == job.job_id
    assert new.lease_id != job.lease_id
    with pytest.raises(SessionRelayError, match="no longer an unstarted lease"):
        _release(conn, job)


def test_termination_release_preserves_reap_for_next_claim():
    conn = _connection()
    _wake(conn, "worker-a", "mail-a")
    conn.execute(
        "INSERT INTO session_termination_reaps "
        "(target_session_id,machine_id,project_id,state,requested_at) "
        "VALUES ('worker-a',?,10,'pending',?)",
        (MACHINE_ID, NOW),
    )
    conn.commit()
    job = next(j for j in _claim(conn) if j.job_kind == "terminate")
    _release(conn, job)
    _release(conn, job)
    new = next(j for j in _claim(conn, 2) if j.job_kind == "terminate")
    assert new.job_id == job.job_id
    assert new.lease_id != job.lease_id


@pytest.mark.parametrize("started", [False, True])
def test_release_refuses_wrong_lease_or_started_launch(started):
    conn = _connection()
    launch = assigned_launch(conn, key="protected", machine_id=MACHINE_ID)
    job = _claim(conn)[0]
    if started:
        report_relay_job(
            conn,
            actor_id=1,
            relay_id=RELAY_ID,
            job_kind="launch",
            job_id=job.job_id,
            lease_id=job.lease_id,
            result_code="progress",
            evidence={"native_launch_phase": "adapter_start"},
            now=NOW,
        )
        overrides = {}
    else:
        overrides = {"lease_id": "wrong-lease"}
    with pytest.raises(SessionRelayError, match="no longer an unstarted lease"):
        _release(conn, job, **overrides)
    assert get_launch(conn, launch.launch_id).state == "launching"


def test_release_cannot_requeue_a_wake_with_an_observed_native_outcome():
    conn = _connection()
    _wake(conn, "worker-a", "mail-a")
    job = _claim(conn)[0]
    conn.execute(
        "UPDATE session_message_attempts SET result_code='native_created' WHERE attempt_id=?",
        (job.job_id,),
    )
    conn.commit()
    with pytest.raises(SessionRelayError, match="no longer an unstarted lease"):
        _release(conn, job)
    assert _claim(conn, 2) == ()
