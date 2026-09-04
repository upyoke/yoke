"""Wake settlement from the receipt the wake was sent to deliver."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.session_launch_test_support import relay_connection
from runtime.api.domain.test_session_relay import (
    RELAY_ID,
    _add_wake_recipient,
    _clock,
    _connection as relay_job_connection,
    _heartbeat,
)
from yoke_contracts.session_control.resume import (
    RESUME_NEVER_STARTED_RESULT,
    RESUME_RUNAWAY_RESULT,
    RESUMED_DIED_RESULT,
    RESUMED_RUNNING_RESULT,
)
from yoke_contracts.session_control.wake_delivery import (
    TURN_WITHOUT_INJECTION_RESULT,
)
from yoke_core.domain.session_wake_reconciliation import (
    EVENT_SESSION_WAKE_OUTCOME_RECORDED,
    reconcile_spawned_wake_attempts,
)
from yoke_core.domain.session_relay import claim_relay_job, report_relay_job


STARTED = "2026-08-22T12:00:00Z"


def _add_events_table(conn) -> None:
    conn.execute(
        "CREATE TABLE events ("
        "event_id TEXT PRIMARY KEY,event_name TEXT,event_kind TEXT,event_type TEXT,"
        "source_type TEXT,session_id TEXT,severity TEXT,event_outcome TEXT,"
        "org_id TEXT,environment TEXT,service TEXT,project_id INTEGER,"
        "actor_id INTEGER,item_id TEXT,task_num INTEGER,agent TEXT,tool_name TEXT,"
        "duration_ms INTEGER,exit_code INTEGER,trace_id TEXT,anomaly_flags TEXT,"
        "tool_use_id TEXT,turn_id TEXT,hook_event_name TEXT,client_timing_id TEXT,"
        "envelope TEXT,"
        "created_at TEXT)"
    )


def _connection():
    conn = relay_connection()
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id,project_id,executor,executor_surface,executor_version,"
        "machine_id,model,offered_at,turn_posture,turn_posture_at,last_tool_call_at) "
        "VALUES ('target',10,'claude-code','claude-cli','2.1.238','machine-1',"
        "'claude-opus-4-1',?,'unknown',NULL,NULL)",
        (STARTED,),
    )
    conn.execute(
        "INSERT INTO session_messages "
        "(message_id,sender_actor_id,body,body_sha256,selector_snapshot,"
        "created_at,expires_at) VALUES ('message-1',1,'private','sha','{}',?,?)",
        (STARTED, "2026-08-23T12:00:00Z"),
    )
    conn.execute(
        "INSERT INTO session_message_recipients "
        "(message_id,session_id,project_id,resolution_evidence,routing_snapshot,"
        "state,created_at,wake_after) VALUES "
        "('message-1','target',10,'{}','{}','pending',?,?)",
        (STARTED, STARTED),
    )
    conn.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id,message_id,target_session_id,attempt_kind,started_at,"
        "result_code,evidence) VALUES "
        "('attempt-1','message-1','target','wake_relay',?,?,?)",
        (
            STARTED,
            RESUMED_RUNNING_RESULT,
            json.dumps(
                {
                    "native_pid": 4321,
                    "native_binary": "/opt/claude",
                    "result_code": RESUMED_RUNNING_RESULT,
                }
            ),
        ),
    )
    conn.commit()
    return conn


def test_a_finished_resume_that_delivered_nothing_is_named_a_failure() -> None:
    conn = _connection()
    _add_events_table(conn)
    conn.execute(
        "UPDATE harness_sessions SET turn_posture='waiting',turn_posture_at=? "
        "WHERE session_id='target'",
        ("2026-08-22T12:00:20Z",),
    )

    changed = reconcile_spawned_wake_attempts(
        conn,
        now="2026-08-22T12:00:30Z",
    )
    conn.commit()

    attempt = conn.execute(
        "SELECT completed_at,result_code,evidence FROM session_message_attempts"
    ).fetchone()
    assert changed == 1
    assert tuple(attempt[:2]) == (
        "2026-08-22T12:00:30Z",
        TURN_WITHOUT_INJECTION_RESULT,
    )
    evidence = json.loads(attempt[2])
    assert evidence["native_pid"] == 4321
    assert evidence["result_code"] == TURN_WITHOUT_INJECTION_RESULT
    # The transport observation the verdict replaced stays readable.
    assert evidence["transport_result"] == RESUMED_RUNNING_RESULT
    assert evidence["injection_count"] == 0
    event = conn.execute(
        "SELECT event_name,session_id,event_outcome,envelope FROM events"
    ).fetchone()
    assert tuple(event[:3]) == (
        EVENT_SESSION_WAKE_OUTCOME_RECORDED,
        "target",
        "failed",
    )
    assert json.loads(event[3])["context"]["attempt_id"] == "attempt-1"


@pytest.mark.parametrize(
    ("posture_at", "tool_at", "now", "expected"),
    (
        (
            "2026-08-22T12:01:00Z",
            "2026-08-22T12:02:00Z",
            "2026-08-22T12:22:01Z",
            RESUMED_DIED_RESULT,
        ),
        (None, None, "2026-08-22T12:20:01Z", RESUME_NEVER_STARTED_RESULT),
        (
            "2026-08-22T12:59:30Z",
            None,
            "2026-08-22T13:00:01Z",
            RESUME_RUNAWAY_RESULT,
        ),
    ),
)
def test_inactivity_and_runaway_settle_truthful_failure(
    posture_at: str | None,
    tool_at: str | None,
    now: str,
    expected: str,
) -> None:
    conn = _connection()
    conn.execute(
        "UPDATE harness_sessions SET turn_posture='running',turn_posture_at=?,"
        "last_tool_call_at=? WHERE session_id='target'",
        (posture_at, tool_at),
    )

    assert reconcile_spawned_wake_attempts(conn, now=now) == 1
    row = conn.execute(
        "SELECT completed_at,result_code FROM session_message_attempts"
    ).fetchone()
    assert tuple(row) == (now, expected)


def test_recent_running_activity_keeps_attempt_open() -> None:
    conn = _connection()
    conn.execute(
        "UPDATE harness_sessions SET turn_posture='running',turn_posture_at=? "
        "WHERE session_id='target'",
        ("2026-08-22T12:10:00Z",),
    )

    assert reconcile_spawned_wake_attempts(conn, now="2026-08-22T12:20:00Z") == 0
    row = conn.execute(
        "SELECT completed_at,result_code FROM session_message_attempts"
    ).fetchone()
    assert tuple(row) == (None, RESUMED_RUNNING_RESULT)


def test_spawn_report_releases_relay_batch_but_keeps_attempt_open() -> None:
    conn = relay_job_connection()
    _add_wake_recipient(conn)
    claimed = claim_relay_job(conn, _heartbeat(), wait_seconds=0, now_provider=_clock())
    job = claimed.jobs[0]

    first = report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="wake",
        job_id=job.job_id,
        lease_id=job.lease_id,
        result_code=RESUMED_RUNNING_RESULT,
        adapter_revision="claude-native-v3",
        evidence={"native_pid": 4321, "native_binary": "/opt/claude"},
        now="2026-08-22T12:00:10Z",
    )
    duplicate = report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="wake",
        job_id=job.job_id,
        lease_id=job.lease_id,
        result_code=RESUMED_RUNNING_RESULT,
        now="2026-08-22T12:00:11Z",
    )

    assert duplicate == first
    attempt = conn.execute(
        "SELECT completed_at,result_code,evidence FROM session_message_attempts"
    ).fetchone()
    assert attempt[0] is None and attempt[1] == RESUMED_RUNNING_RESULT
    assert json.loads(attempt[2])["native_pid"] == 4321
    relay = conn.execute(
        "SELECT lease_id,lease_expires_at FROM session_relays WHERE relay_id=?",
        (RELAY_ID,),
    ).fetchone()
    assert tuple(relay) == (None, None)
