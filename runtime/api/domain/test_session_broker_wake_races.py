"""Target-change and version-race coverage for brokered wakes."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from yoke_core.domain.session_broker_wake import lease_broker_wake_for_hook
from yoke_core.domain.session_broker_wake_settlement import (
    complete_broker_hook_lease,
    settle_broker_wake_losses,
)
from yoke_core.domain.session_message_service import send_message
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
from runtime.api.domain.test_session_message_support import selector


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


def _claim_broker(conn, lease_id: str, broker: str, seconds: int):
    return claim_relay_job(
        conn,
        _heartbeat(),
        wait_seconds=0,
        broker_only=True,
        broker_lease_id=lease_id,
        broker_session_id=broker,
        now_provider=lambda: _stamp(seconds=seconds),
    )


def test_target_hook_activity_closes_broker_job_before_native_mutation() -> None:
    conn, _message_id = _seed()
    lease = _instruct(conn)
    conn.execute(
        "UPDATE harness_sessions SET ended_at=NULL,last_heartbeat=?,"
        "turn_posture='running',turn_posture_at=? "
        "WHERE session_id='s4'",
        (_stamp(seconds=3), _stamp(seconds=3)),
    )
    conn.commit()

    outcome = _claim_broker(conn, lease.lease_id, "broker-a", 4)

    assert outcome.jobs == ()
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
        == 1
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
        broker_lease_id=lease.lease_id,
        broker_session_id="broker-a",
        now_provider=lambda: _stamp(seconds=3),
    )

    assert outcome.jobs == ()
    row = conn.execute(
        "SELECT completed_at,result_code FROM session_message_attempts "
        "WHERE attempt_id=?",
        (lease.attempt_id,),
    ).fetchone()
    assert tuple(row) == (_stamp(seconds=3), "version_mismatch")
    assert (
        conn.execute(
            "SELECT wake_attempt_count FROM session_message_recipients"
        ).fetchone()[0]
        == 1
    )


def test_connected_relay_without_target_project_skips_broker() -> None:
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

    assert direct.jobs == ()
    assert broker is None


def test_broker_native_failure_settles_the_reserved_attempt() -> None:
    conn, _message_id = _seed()
    lease = _instruct(conn)
    outcome = _claim_broker(conn, lease.lease_id, "broker-a", 3)
    assert outcome.jobs

    report_relay_job(
        conn,
        actor_id=10,
        relay_id=RELAY_ID,
        job_kind="wake",
        job_id=outcome.jobs[0].job_id,
        lease_id=outcome.jobs[0].lease_id,
        result_code="failed",
        now=_stamp(seconds=4),
    )

    row = conn.execute(
        "SELECT completed_at,result_code FROM session_message_attempts "
        "WHERE attempt_id=?",
        (lease.attempt_id,),
    ).fetchone()
    assert tuple(row) == (_stamp(seconds=4), "failed")


def test_broker_claim_is_scoped_to_exact_lease_and_verified_peer() -> None:
    conn, _message_id = _seed()
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id,project_id,executor,executor_surface,executor_version,"
        "machine_id,execution_lane,last_heartbeat,last_tool_call_at,offered_at,"
        "ended_at,turn_posture,turn_posture_at) VALUES "
        "('s5',1,'codex','codex-cli','0.148.0a15',?,'direct',?,?,?,?,"
        "'waiting',?)",
        (MACHINE_ID, _stamp(), _stamp(), _stamp(), _stamp(), _stamp()),
    )
    send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=["s5"]),
        body="Second exact-lease wake",
        now=NOW - timedelta(minutes=11),
    )
    first = _reserve(conn, "broker-a")
    second = _reserve(conn, "broker-b")
    assert first is not None and second is not None
    for lease in (first, second):
        complete_broker_hook_lease(
            conn,
            lease_id=lease.lease_id,
            delivered=True,
            result="injected",
            now=NOW + timedelta(seconds=2),
        )

    claimed_second = _claim_broker(conn, second.lease_id, "broker-b", 3)
    assert len(claimed_second.jobs) == 1
    assert claimed_second.jobs[0].job_id == second.attempt_id
    report_relay_job(
        conn,
        actor_id=10,
        relay_id=RELAY_ID,
        job_kind="wake",
        job_id=second.attempt_id,
        lease_id=second.lease_id,
        result_code="accepted",
        now=_stamp(seconds=4),
    )

    claimed_first = _claim_broker(conn, first.lease_id, "broker-a", 5)
    assert len(claimed_first.jobs) == 1
    assert claimed_first.jobs[0].job_id == first.attempt_id


def test_wrong_or_stale_broker_lease_cannot_claim_a_new_reservation() -> None:
    conn, _message_id = _seed()
    stale = _instruct(conn)
    settle_broker_wake_losses(
        conn,
        now=NOW + timedelta(seconds=301),
    )
    current = lease_broker_wake_for_hook(
        conn,
        broker_session_id="broker-a",
        hook_event="PreToolUse",
        now=NOW + timedelta(seconds=302),
    )
    assert current is not None
    complete_broker_hook_lease(
        conn,
        lease_id=current.lease_id,
        delivered=True,
        result="injected",
        now=NOW + timedelta(seconds=303),
    )

    wrong = _claim_broker(conn, stale.lease_id, "broker-a", 304)
    assert wrong.jobs == ()
    row = conn.execute(
        "SELECT result_code,completed_at FROM session_message_attempts "
        "WHERE attempt_id=?",
        (current.attempt_id,),
    ).fetchone()
    assert tuple(row) == ("broker_instructed", None)


def test_ordinary_relay_poll_does_not_steal_broker_reservation() -> None:
    conn, _message_id = _seed()
    lease = _instruct(conn)

    ordinary = claim_relay_job(
        conn,
        _heartbeat(),
        wait_seconds=0,
        now_provider=lambda: _stamp(seconds=3),
    )

    assert ordinary.jobs == ()
    row = conn.execute(
        "SELECT result_code,completed_at FROM session_message_attempts "
        "WHERE attempt_id=?",
        (lease.attempt_id,),
    ).fetchone()
    assert tuple(row) == ("broker_instructed", None)


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
    assert (
        conn.execute(
            "SELECT wake_attempt_count FROM session_message_recipients"
        ).fetchone()[0]
        == 3
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
                ).jobs
                != ()
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
