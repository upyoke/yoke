"""Target-change and version-race coverage for brokered wakes."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from yoke_core.domain.session_broker_wake import lease_broker_wake_for_hook
from yoke_core.domain.session_broker_wake_settlement import (
    complete_broker_hook_lease,
)
from yoke_core.domain.session_relay import claim_relay_job, report_relay_job
from yoke_core.domain.session_relay_types import RelayHeartbeat
from runtime.api.domain.test_session_broker_wake import (
    MACHINE_ID,
    NOW,
    RELAY_ID,
    _heartbeat,
    _reserve,
    _seed,
    _stamp,
)


def _instruct(conn):
    lease = _reserve(conn)
    assert lease
    complete_broker_hook_lease(
        conn,
        lease_id=lease.lease_id,
        delivered=True,
        result="injected",
        now=NOW + timedelta(seconds=2),
    )
    return lease


def test_target_hook_activity_closes_broker_job_before_native_mutation() -> None:
    conn, _message_id = _seed()
    lease = _instruct(conn)
    conn.execute(
        "UPDATE harness_sessions SET turn_posture='running',turn_posture_at=? "
        "WHERE session_id='s4'",
        (_stamp(seconds=3),),
    )
    conn.commit()

    outcome = claim_relay_job(
        conn,
        _heartbeat(),
        wait_seconds=0,
        broker_only=True,
        now_provider=lambda: _stamp(seconds=4),
    )

    assert outcome.job is None
    row = conn.execute(
        "SELECT completed_at,result_code FROM session_message_attempts "
        "WHERE attempt_id=?",
        (lease.attempt_id,),
    ).fetchone()
    assert row[0] == _stamp(seconds=4)
    assert row[1] == "broker_target_changed"
    assert (
        conn.execute(
            "SELECT wake_attempt_count FROM session_message_recipients"
        ).fetchone()[0]
        == 0
    )


def test_broker_version_mismatch_is_terminal_and_typed() -> None:
    conn, _message_id = _seed()
    lease = _instruct(conn)
    mismatch = RelayHeartbeat(
        relay_id=RELAY_ID,
        actor_id=10,
        machine_id=MACHINE_ID,
        hostname="broker-host",
        relay_version="0.1.1",
        surface_versions={"codex-cli": "not-a-version"},
        project_ids=(1,),
    )

    outcome = claim_relay_job(
        conn,
        mismatch,
        wait_seconds=0,
        broker_only=True,
        now_provider=lambda: _stamp(seconds=3),
    )

    assert outcome.job is None
    row = conn.execute(
        "SELECT completed_at,result_code FROM session_message_attempts "
        "WHERE attempt_id=?",
        (lease.attempt_id,),
    ).fetchone()
    assert row[0] == _stamp(seconds=3)
    assert row[1] == "version_mismatch"


def test_connected_relay_without_target_project_does_not_block_broker() -> None:
    conn, _message_id = _seed()
    unrelated = RelayHeartbeat(
        relay_id=RELAY_ID,
        actor_id=10,
        machine_id=MACHINE_ID,
        hostname="broker-host",
        relay_version="0.1.1",
        surface_versions={"codex-cli": "0.148.0a15"},
        project_ids=(),
    )

    direct = claim_relay_job(
        conn,
        unrelated,
        wait_seconds=0,
        now_provider=lambda: _stamp(seconds=1),
    )
    broker = _reserve(conn)

    assert direct.job is None
    assert broker is not None


def test_broker_native_failure_settles_the_reserved_attempt() -> None:
    conn, _message_id = _seed()
    lease = _instruct(conn)
    outcome = claim_relay_job(
        conn,
        _heartbeat(),
        wait_seconds=0,
        broker_only=True,
        now_provider=lambda: _stamp(seconds=3),
    )
    assert outcome.job

    report_relay_job(
        conn,
        actor_id=10,
        relay_id=RELAY_ID,
        job_kind="wake",
        job_id=outcome.job.job_id,
        lease_id=outcome.job.lease_id,
        result_code="failed",
        now=_stamp(seconds=4),
    )

    row = conn.execute(
        "SELECT completed_at,result_code FROM session_message_attempts "
        "WHERE attempt_id=?",
        (lease.attempt_id,),
    ).fetchone()
    assert tuple(row) == (_stamp(seconds=4), "failed")


def test_render_failures_are_bounded_by_the_wake_retry_policy() -> None:
    conn, _message_id = _seed()

    for offset in range(1, 4):
        lease = lease_broker_wake_for_hook(
            conn,
            broker_session_id="broker-a",
            hook_event="PreToolUse",
            now=NOW + timedelta(seconds=offset * 2),
        )
        assert lease
        complete_broker_hook_lease(
            conn,
            lease_id=lease.lease_id,
            delivered=False,
            result="render_output_missing",
            now=NOW + timedelta(seconds=offset * 2 + 1),
        )

    assert (
        lease_broker_wake_for_hook(
            conn,
            broker_session_id="broker-a",
            hook_event="PreToolUse",
            now=NOW + timedelta(seconds=10),
        )
        is None
    )


def test_direct_and_broker_claims_share_one_recipient_cas(tmp_path) -> None:
    path = tmp_path / "direct-broker.sqlite"
    conn, _message_id = _seed(str(path))
    conn.close()

    def compete(route: str) -> bool:
        worker = sqlite3.connect(str(path), timeout=5, check_same_thread=False)
        worker.row_factory = sqlite3.Row
        try:
            if route == "broker":
                return (
                    lease_broker_wake_for_hook(
                        worker,
                        broker_session_id="broker-a",
                        hook_event="PreToolUse",
                        now=NOW + timedelta(seconds=1),
                    )
                    is not None
                )
            return (
                claim_relay_job(
                    worker,
                    _heartbeat(),
                    wait_seconds=0,
                    now_provider=lambda: _stamp(seconds=1),
                ).job
                is not None
            )
        finally:
            worker.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(compete, ("direct", "broker")))

    assert sum(results) == 1
    verify = sqlite3.connect(str(path))
    assert (
        verify.execute(
            "SELECT COUNT(*) FROM session_message_attempts WHERE completed_at IS NULL"
        ).fetchone()[0]
        == 1
    )
