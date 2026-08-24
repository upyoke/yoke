"""One-hop peer broker selection, adoption, loss, and dedupe tests."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from yoke_contracts.session_control.wake_instruction import native_wake_instruction
from yoke_core.domain.session_broker_wake import lease_broker_wake_for_hook
from yoke_core.domain.session_broker_wake_settlement import (
    complete_broker_hook_lease,
    settle_broker_wake_losses,
)
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_relay import claim_relay_job, report_relay_job
from yoke_core.domain.session_relay_types import RelayHeartbeat
from runtime.api.domain.test_session_message_support import (
    NOW,
    NOW_TEXT,
    message_connection,
    selector,
)


MACHINE_ID = "11111111-1111-4111-8111-111111111111"
RELAY_ID = f"machine:{MACHINE_ID}"


def _stamp(minutes: int = 0, seconds: int = 0) -> str:
    return (NOW + timedelta(minutes=minutes, seconds=seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _heartbeat() -> RelayHeartbeat:
    return RelayHeartbeat(
        relay_id=RELAY_ID,
        actor_id=10,
        machine_id=MACHINE_ID,
        hostname="broker-host",
        relay_version="0.1.1",
        surface_versions={"codex-cli": "0.148.0a15"},
        project_ids=(1,),
    )


def _seed(path: str = ":memory:"):
    conn = message_connection(path)
    conn.execute(
        "UPDATE harness_sessions SET machine_id=?,turn_posture='waiting',"
        "turn_posture_at=? WHERE session_id='s4'",
        (MACHINE_ID, NOW_TEXT),
    )
    for broker in ("broker-a", "broker-b"):
        conn.execute(
            "INSERT INTO harness_sessions "
            "(session_id,project_id,executor,executor_surface,executor_version,"
            "machine_id,execution_lane,last_heartbeat,last_tool_call_at,offered_at,"
            "turn_posture,turn_posture_at) VALUES "
            "(?,1,'codex','codex-desktop','26.818.31338',?,'direct',?,?,?,"
            "'running',?)",
            (broker, MACHINE_ID, NOW_TEXT, NOW_TEXT, NOW_TEXT, NOW_TEXT),
        )
    conn.commit()
    message_id = send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=["s4"]),
        body="Secret body must never enter broker or native traffic.",
        now=NOW,
    )["message_id"]
    return conn, message_id


def _reserve(conn, broker: str = "broker-a"):
    return lease_broker_wake_for_hook(
        conn,
        broker_session_id=broker,
        hook_event="PreToolUse",
        now=NOW + timedelta(seconds=1),
    )


def test_broker_hook_reserves_then_existing_relay_executes_same_attempt() -> None:
    conn, message_id = _seed()
    lease = _reserve(conn)

    assert lease and lease.command == (
        f"yoke relay serve-once --broker --broker-lease {lease.lease_id}"
    )
    attempt = conn.execute(
        "SELECT attempt_id,attempt_kind,broker_session_id,result_code,evidence "
        "FROM session_message_attempts"
    ).fetchone()
    assert tuple(attempt[:4]) == (
        lease.attempt_id,
        "wake_broker",
        "broker-a",
        "broker_hook_leased",
    )
    assert "Secret body" not in attempt[4]
    wake_count = conn.execute(
        "SELECT wake_attempt_count FROM session_message_recipients"
    ).fetchone()[0]
    assert wake_count == 0

    complete_broker_hook_lease(
        conn,
        lease_id=lease.lease_id,
        delivered=True,
        result="injected",
        now=NOW + timedelta(seconds=2),
    )
    claimed = claim_relay_job(
        conn,
        _heartbeat(),
        wait_seconds=0,
        broker_only=True,
        broker_lease_id=lease.lease_id,
        broker_session_id="broker-a",
        now_provider=lambda: _stamp(seconds=3),
    )

    assert claimed.job and claimed.job.job_id == lease.attempt_id
    assert claimed.job.message_id == message_id
    assert claimed.job.native_instruction == native_wake_instruction(message_id)
    assert "Secret body" not in claimed.job.native_instruction
    wake_count = conn.execute(
        "SELECT wake_attempt_count FROM session_message_recipients"
    ).fetchone()[0]
    assert wake_count == 1
    report_relay_job(
        conn,
        actor_id=10,
        relay_id=RELAY_ID,
        job_kind="wake",
        job_id=lease.attempt_id,
        lease_id=lease.lease_id,
        result_code="accepted",
        adapter_revision="codex-relay-v4",
        now=_stamp(seconds=4),
    )
    final = conn.execute(
        "SELECT completed_at,result_code,adapter_revision "
        "FROM session_message_attempts WHERE attempt_id=?",
        (lease.attempt_id,),
    ).fetchone()
    assert tuple(final) == (_stamp(seconds=4), "accepted", "codex-relay-v4")


def test_failed_direct_route_waits_for_and_immediately_offers_broker() -> None:
    conn, _message_id = _seed()
    direct = claim_relay_job(
        conn,
        _heartbeat(),
        wait_seconds=0,
        now_provider=lambda: _stamp(seconds=1),
    )
    assert direct.job
    report_relay_job(
        conn,
        actor_id=10,
        relay_id=RELAY_ID,
        job_kind="wake",
        job_id=direct.job.job_id,
        lease_id=direct.job.lease_id,
        result_code="failed",
        now=_stamp(seconds=2),
    )

    repeat = claim_relay_job(
        conn,
        _heartbeat(),
        wait_seconds=0,
        now_provider=lambda: _stamp(seconds=3),
    )
    broker = lease_broker_wake_for_hook(
        conn,
        broker_session_id="broker-a",
        hook_event="PreToolUse",
        now=NOW + timedelta(seconds=3),
    )

    assert repeat.job is None
    assert broker is not None
    assert (
        conn.execute(
            "SELECT wake_attempt_count FROM session_message_recipients"
        ).fetchone()[0]
        == 1
    )


def test_connected_direct_route_prevents_broker_before_a_failure() -> None:
    conn, _message_id = _seed()
    claim_relay_job(
        conn,
        _heartbeat(),
        wait_seconds=0,
        now_provider=lambda: _stamp(seconds=1),
    )

    assert (
        lease_broker_wake_for_hook(
            conn,
            broker_session_id="broker-a",
            hook_event="PostToolUse",
            now=NOW + timedelta(seconds=2),
        )
        is None
    )


def test_failed_direct_route_retries_after_bounded_broker_window() -> None:
    conn, _message_id = _seed()
    direct = claim_relay_job(
        conn,
        _heartbeat(),
        wait_seconds=0,
        now_provider=lambda: _stamp(seconds=1),
    )
    assert direct.job
    report_relay_job(
        conn,
        actor_id=10,
        relay_id=RELAY_ID,
        job_kind="wake",
        job_id=direct.job.job_id,
        lease_id=direct.job.lease_id,
        result_code="failed",
        now=_stamp(seconds=2),
    )

    retried = claim_relay_job(
        conn,
        _heartbeat(),
        wait_seconds=0,
        now_provider=lambda: _stamp(minutes=11),
    )

    assert retried.job and retried.job.job_kind == "wake"
    assert retried.job.job_id != direct.job.job_id


def test_broker_loss_and_dropped_render_settle_without_consuming_retry() -> None:
    conn, _message_id = _seed()
    dropped = _reserve(conn)
    assert dropped
    complete_broker_hook_lease(
        conn,
        lease_id=dropped.lease_id,
        delivered=False,
        result="dropped_by_sibling_denial",
        now=NOW + timedelta(seconds=2),
    )
    row = conn.execute(
        "SELECT completed_at,result_code FROM session_message_attempts"
    ).fetchone()
    assert row[1] == "broker_render_dropped"

    second = lease_broker_wake_for_hook(
        conn,
        broker_session_id="broker-a",
        hook_event="PreToolUse",
        now=NOW + timedelta(seconds=3),
    )
    assert second
    complete_broker_hook_lease(
        conn,
        lease_id=second.lease_id,
        delivered=True,
        result="injected",
        now=NOW + timedelta(seconds=4),
    )
    conn.execute(
        "UPDATE harness_sessions SET turn_posture='waiting' WHERE session_id='broker-a'"
    )
    conn.commit()

    assert settle_broker_wake_losses(conn, now=NOW + timedelta(seconds=34)) == 1
    lost = conn.execute(
        "SELECT result_code FROM session_message_attempts WHERE attempt_id=?",
        (second.attempt_id,),
    ).fetchone()[0]
    assert lost == "broker_lost"
    assert (
        conn.execute(
            "SELECT wake_attempt_count FROM session_message_recipients"
        ).fetchone()[0]
        == 0
    )


def test_open_broker_roles_cannot_recursively_broker_or_duplicate() -> None:
    conn, _message_id = _seed()
    first = _reserve(conn)
    assert first

    assert _reserve(conn) is None
    assert (
        lease_broker_wake_for_hook(
            conn,
            broker_session_id="s4",
            hook_event="PreToolUse",
            now=NOW + timedelta(seconds=2),
        )
        is None
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM session_message_attempts "
            "WHERE attempt_kind='wake_broker' AND completed_at IS NULL"
        ).fetchone()[0]
        == 1
    )


def test_concurrent_peers_reserve_exactly_one_broker_attempt(tmp_path) -> None:
    path = tmp_path / "broker.sqlite"
    conn, _message_id = _seed(str(path))
    conn.close()

    def reserve(broker: str):
        worker = sqlite3.connect(str(path), timeout=5, check_same_thread=False)
        worker.row_factory = sqlite3.Row
        try:
            return lease_broker_wake_for_hook(
                worker,
                broker_session_id=broker,
                hook_event="PreToolUse",
                now=NOW + timedelta(seconds=1),
            )
        finally:
            worker.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, ("broker-a", "broker-b")))

    assert sum(result is not None for result in results) == 1
    verify = sqlite3.connect(str(path))
    assert (
        verify.execute(
            "SELECT COUNT(*) FROM session_message_attempts "
            "WHERE attempt_kind='wake_broker' AND completed_at IS NULL"
        ).fetchone()[0]
        == 1
    )
