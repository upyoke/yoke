"""Focused recovery tests for launch-attempt reconciliation."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.session_launch_deadlines import settle_launch_deadlines
from yoke_core.domain.session_launch_execution import reconcile_launch
from yoke_core.domain.session_launch_requests import cancel_launch
from yoke_core.domain.session_launch_store import get_launch
from yoke_core.domain.session_launch_types import SessionLaunchError
from yoke_core.domain.session_relay import claim_relay_job
from yoke_core.domain.session_relay_types import RelayHeartbeat
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    authorization,
    launch_connection,
)


MACHINE_ID = "11111111-1111-4111-8111-111111111111"
RELAY_ID = f"machine:{MACHINE_ID}"


def _connection():
    conn = launch_connection()
    conn.execute("ALTER TABLE projects ADD COLUMN org_id INTEGER DEFAULT 1")
    conn.execute("CREATE TABLE organizations (id INTEGER PRIMARY KEY, settings TEXT)")
    conn.execute("INSERT INTO organizations VALUES (1, '{}')")
    for column in (
        "executor TEXT DEFAULT 'codex'",
        "execution_lane TEXT",
        "last_heartbeat TEXT",
        "offered_at TEXT",
        "ended_at TEXT",
        "last_tool_call_at TEXT",
        "turn_posture TEXT NOT NULL DEFAULT 'unknown'",
        "turn_posture_at TEXT",
    ):
        conn.execute(f"ALTER TABLE harness_sessions ADD COLUMN {column}")
    conn.commit()
    return conn


def _heartbeat() -> RelayHeartbeat:
    return RelayHeartbeat(
        relay_id=RELAY_ID,
        actor_id=1,
        machine_id=MACHINE_ID,
        hostname="relay-host",
        relay_version="0.1.1",
        surface_versions={"codex-cli": "0.148.0a15"},
        project_ids=(10,),
    )


def _claimed_launch(conn, *, key: str):
    add_relay(conn, relay_id=RELAY_ID, machine_id=MACHINE_ID)
    launch = assigned_launch(conn, key=key, machine_id=MACHINE_ID)
    outcome = claim_relay_job(
        conn,
        _heartbeat(),
        wait_seconds=0,
        now_provider=lambda: NOW,
    )
    assert outcome.job and outcome.job.job_kind == "launch"
    return launch, outcome.job


def test_reconciliation_refuses_an_unexpired_relay_lease() -> None:
    conn = _connection()
    launch, job = _claimed_launch(conn, key="live-reconcile-lease")
    cancel_launch(
        conn,
        launch_id=launch.launch_id,
        auth=authorization(),
        now="2026-08-22T12:00:10Z",
    )

    with pytest.raises(SessionLaunchError) as refused:
        reconcile_launch(
            conn,
            launch_id=launch.launch_id,
            auth=authorization(),
            observed_native_id=None,
            now="2026-08-22T12:00:11Z",
        )

    assert refused.value.code == "relay_lease_active"
    assert get_launch(conn, launch.launch_id).state == "outcome_unknown"
    attempt = conn.execute(
        "SELECT completed_at FROM session_launch_attempts WHERE launch_id=?",
        (launch.launch_id,),
    ).fetchone()
    relay = conn.execute(
        "SELECT lease_id FROM session_relays WHERE relay_id=?", (RELAY_ID,)
    ).fetchone()
    assert attempt[0] is None
    assert relay[0] == job.lease_id


def test_expired_reconciliation_releases_relay_for_the_next_launch() -> None:
    conn = _connection()
    launch, _job = _claimed_launch(conn, key="expired-reconcile-lease")
    settle_launch_deadlines(conn, now="2026-08-22T12:05:01Z")

    reconciled = reconcile_launch(
        conn,
        launch_id=launch.launch_id,
        auth=authorization(),
        observed_native_id=None,
        now="2026-08-22T12:05:02Z",
    )

    assert reconciled.result_code == "reconciled_not_created"
    attempt = conn.execute(
        "SELECT completed_at,result_code,evidence FROM session_launch_attempts "
        "WHERE launch_id=?",
        (launch.launch_id,),
    ).fetchone()
    assert tuple(attempt[:2]) == ("2026-08-22T12:05:02Z", "not_created")
    assert json.loads(attempt[2]) == {"result_code": "reconciled_not_created"}
    assert (
        conn.execute(
            "SELECT lease_id FROM session_relays WHERE relay_id=?", (RELAY_ID,)
        ).fetchone()[0]
        is None
    )

    next_launch = assigned_launch(
        conn,
        key="launch-after-reconciliation",
        machine_id=MACHINE_ID,
    )
    next_claim = claim_relay_job(
        conn,
        _heartbeat(),
        wait_seconds=0,
        now_provider=lambda: "2026-08-22T12:05:03Z",
    )
    assert next_claim.job and next_claim.job.job_id == next_launch.launch_id


def test_native_reconciliation_refuses_multiple_open_attempts() -> None:
    conn = _connection()
    launch, _job = _claimed_launch(conn, key="ambiguous-native-reconciliation")
    cancel_launch(
        conn,
        launch_id=launch.launch_id,
        auth=authorization(),
        now="2026-08-22T12:00:10Z",
    )
    conn.execute(
        "INSERT INTO session_launch_attempts "
        "(attempt_id,launch_id,relay_id,machine_id,lease_id,attempt_number,started_at) "
        "VALUES ('attempt-2',?,'relay-2',?,'lease-2',2,'2026-08-22T12:00:01Z')",
        (launch.launch_id, MACHINE_ID),
    )
    conn.commit()

    with pytest.raises(SessionLaunchError) as refused:
        reconcile_launch(
            conn,
            launch_id=launch.launch_id,
            auth=authorization(),
            observed_native_id="native-session",
            now="2026-08-22T12:06:00Z",
        )

    assert refused.value.code == "reconciliation_attempt_ambiguous"
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM session_launch_attempts WHERE completed_at IS NULL"
        ).fetchone()[0]
        == 2
    )


def test_repeat_reconciliation_repairs_a_legacy_attempt_once() -> None:
    conn = _connection()
    launch, _job = _claimed_launch(conn, key="legacy-reconcile-lease")
    settle_launch_deadlines(conn, now="2026-08-22T12:05:01Z")
    conn.execute(
        "UPDATE session_launches SET state='failed',attestation_hash=NULL,"
        "completed_at='2026-08-22T12:05:02Z',"
        "result_code='reconciled_not_created' WHERE launch_id=?",
        (launch.launch_id,),
    )
    conn.execute(
        "UPDATE session_relays SET lease_id='newer-lease',"
        "lease_expires_at='2026-08-22T12:10:00Z' WHERE relay_id=?",
        (RELAY_ID,),
    )
    conn.commit()

    first = reconcile_launch(
        conn,
        launch_id=launch.launch_id,
        auth=authorization(),
        observed_native_id=None,
        now="2026-08-22T12:06:00Z",
    )
    second = reconcile_launch(
        conn,
        launch_id=launch.launch_id,
        auth=authorization(),
        observed_native_id=None,
        now="2026-08-22T12:07:00Z",
    )

    attempt = conn.execute(
        "SELECT completed_at,result_code FROM session_launch_attempts "
        "WHERE launch_id=?",
        (launch.launch_id,),
    ).fetchone()
    relay = conn.execute(
        "SELECT lease_id,lease_expires_at FROM session_relays WHERE relay_id=?",
        (RELAY_ID,),
    ).fetchone()
    assert first.completed_at == second.completed_at == "2026-08-22T12:05:02Z"
    assert tuple(attempt) == ("2026-08-22T12:06:00Z", "not_created")
    assert tuple(relay) == ("newer-lease", "2026-08-22T12:10:00Z")
