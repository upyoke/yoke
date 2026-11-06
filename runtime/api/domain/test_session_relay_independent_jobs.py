"""Independent queue admissions and job-owned settlement horizons."""

from runtime.api.domain.session_relay_independent_jobs_test_support import (
    _claim as _claim,
    _connection as _connection,
    _fetch as _fetch,
    _wake as _wake,
)


from datetime import timedelta

import pytest

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.session_relay import report_relay_job
from yoke_core.domain.session_relay_expiry import settle_expired_relay_leases
from yoke_core.domain.session_relay_types import SessionRelayError
from runtime.api.domain.session_relay_test_support import (
    MACHINE_ID,
    NOW,
    RELAY_ID,
)
from runtime.api.domain.session_launch_test_support import assigned_launch


def _report(conn, job, seconds=1):
    return report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind=job.job_kind,
        job_id=job.job_id,
        lease_id=job.lease_id,
        result_code="read" if job.job_kind == "evidence" else "failed",
        now=parse_instant(NOW) + timedelta(seconds=seconds),
    )


def test_wakes_evidence_and_launches_progress_before_unrelated_jobs_settle():
    conn = _connection()
    _wake(conn, "worker-a", "mail-a")
    _fetch(conn, "read-a")
    first = _claim(conn)
    assert [j.job_kind for j in first] == ["wake", "evidence"]
    _wake(conn, "worker-b", "mail-b")
    _fetch(conn, "read-b")
    assigned_launch(conn, key="new-worker", machine_id=MACHINE_ID)
    second = _claim(conn, 5)
    assert [j.job_kind for j in second] == ["wake", "evidence", "launch"]
    assert second[0].target_session_id == "worker-b"
    for job in (*second[:2], *first):
        assert _report(conn, job, 10)["result_code"] in {"read", "failed"}
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM session_message_attempts WHERE completed_at IS NOT NULL"
        ).fetchone()[0]
        == 2
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM session_evidence_fetches WHERE state='succeeded'"
        ).fetchone()[0]
        == 2
    )
    assert _claim(conn, 11) == ()


def test_new_claims_neither_renew_nor_prematurely_expire_older_wakes():
    conn = _connection()
    _wake(conn, "worker-a", "mail-a")
    old = _claim(conn)[0]
    _wake(conn, "worker-b", "mail-b")
    new = _claim(conn, 60)[0]
    with pytest.raises(SessionRelayError, match="lease expired"):
        _report(conn, old, 91)
    assert (
        settle_expired_relay_leases(
            conn, now=parse_instant(NOW) + timedelta(seconds=91)
        )
        == 1
    )
    assert _report(conn, new, 91)["result_code"] == "failed"
    assert (
        conn.execute(
            "SELECT result_code FROM session_message_attempts WHERE attempt_id=?",
            (old.job_id,),
        ).fetchone()[0]
        == "relay_lease_expired"
    )


def test_two_messages_cannot_open_two_native_turns_in_the_same_session():
    conn = _connection()
    _wake(conn, "worker-a", "mail-a")
    _wake(conn, "worker-b", "mail-b")
    conn.execute(
        "UPDATE session_message_recipients SET session_id='worker-a' WHERE message_id='mail-b'"
    )
    conn.commit()
    first = _claim(conn)
    assert len(first) == 1
    assert _claim(conn, 1) == ()
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM session_message_attempts WHERE completed_at IS NULL"
        ).fetchone()[0]
        == 1
    )
