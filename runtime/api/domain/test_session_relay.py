"""Focused heartbeat, wake, launch, lease, and redaction tests for relays."""

from __future__ import annotations

import json

import pytest

from yoke_contracts.session_control.wake_instruction import (
    native_wake_instruction,
    native_wake_instruction_sha256,
)
from yoke_core.domain.session_relay import claim_relay_job, report_relay_job
from yoke_core.domain.session_relay_expiry import settle_expired_relay_leases
from yoke_core.domain.session_relay_types import (
    RelayHeartbeat,
    SessionRelayError,
    WakeMode,
)
from yoke_core.domain.session_relay_versions import (
    surface_operation_supported,
    wake_versions_supported,
)
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    relay_connection,
)


MACHINE_ID = "11111111-1111-4111-8111-111111111111"
RELAY_ID = f"machine:{MACHINE_ID}"


def _connection():
    return relay_connection()


def _heartbeat(**versions: str) -> RelayHeartbeat:
    return RelayHeartbeat(
        relay_id=RELAY_ID,
        actor_id=1,
        machine_id=MACHINE_ID,
        hostname="relay-host",
        relay_version="0.1.1",
        surface_versions=versions or {"codex-cli": "0.148.0a15"},
        project_ids=(10,),
    )


def _clock(value: str = NOW):
    return lambda: value


def _add_wake_recipient(conn, *, message_id: str = "message-1") -> None:
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id,project_id,executor_surface,executor_version,machine_id,"
        "model,offered_at,last_tool_call_at,ended_at,turn_posture) "
        "VALUES ('target',10,'codex-cli','0.148.0a15',?,'gpt-5',?,NULL,?,"
        "'waiting')",
        (
            MACHINE_ID,
            "2026-08-22T10:00:00Z",
            "2026-08-22T10:30:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO session_messages "
        "(message_id,sender_actor_id,body,body_sha256,selector_snapshot,"
        "created_at,expires_at) VALUES (?,1,?,'sha256:body','{}',?,?)",
        (
            message_id,
            "Never send this body through the native wake adapter.",
            "2026-08-22T11:00:00Z",
            "2026-08-23T12:00:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO session_message_recipients "
        "(message_id,session_id,project_id,resolution_evidence,routing_snapshot,"
        "executor_surface,executor_version,machine_id,state,created_at,wake_after) "
        "VALUES (?,'target',10,'{}','{}','codex-cli','0.148.0a15',?,"
        "'pending','2026-08-22T11:00:00Z','2026-08-22T11:10:00Z')",
        (message_id, MACHINE_ID),
    )
    conn.commit()


def test_idle_launch_capable_heartbeat_keeps_active_cadence() -> None:
    conn = _connection()

    outcome = claim_relay_job(
        conn,
        _heartbeat(),
        wait_seconds=0,
        now_provider=_clock(),
    )

    assert outcome.state == "idle"
    assert outcome.next_poll_seconds == 60
    row = conn.execute(
        "SELECT actor_id,hostname,relay_version,surface_versions,"
        "project_checkouts,connected_until "
        "FROM session_relays WHERE relay_id=?",
        (RELAY_ID,),
    ).fetchone()
    assert row[0] == 1
    assert row[1] == "relay-host"
    assert row[2] == "0.1.1"
    assert json.loads(row[3]) == {"codex-cli": "0.148.0a15"}
    assert json.loads(row[4]) == [10]
    assert row[5] == "2026-08-22T12:02:00Z"


def test_idle_non_launch_heartbeat_uses_backoff() -> None:
    conn = _connection()

    outcome = claim_relay_job(
        conn,
        _heartbeat(**{"cursor-desktop": "3.17.8"}),
        wait_seconds=0,
        now_provider=_clock(),
    )

    assert outcome.state == "idle"
    assert outcome.next_poll_seconds == 300


def test_recent_hook_activity_snaps_idle_machine_to_active_cadence() -> None:
    conn = _connection()
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id,project_id,executor_surface,executor_version,machine_id,"
        "model,offered_at,last_tool_call_at) VALUES "
        "('live',10,'codex-cli','0.148.0a15',?,'gpt-5',?,?)",
        (MACHINE_ID, NOW, NOW),
    )
    conn.commit()

    outcome = claim_relay_job(conn, _heartbeat(), wait_seconds=0, now_provider=_clock())

    assert outcome.state == "active"
    assert outcome.next_poll_seconds == 60


def test_wake_claim_carries_only_id_and_report_is_redacted_idempotent() -> None:
    conn = _connection()
    _add_wake_recipient(conn)

    claimed = claim_relay_job(conn, _heartbeat(), wait_seconds=0, now_provider=_clock())

    assert len(claimed.jobs) == 1 and claimed.jobs[0].job_kind == "wake"
    assert claimed.jobs[0].message_id == "message-1"
    assert claimed.jobs[0].surface_version == "0.148.0a15"
    assert claimed.jobs[0].wake_mode is WakeMode.WAITING
    assert claimed.to_dict()["jobs"][0]["wake_mode"] == "waiting"
    assert type(claimed.to_dict()["jobs"][0]["wake_mode"]) is str
    assert claimed.jobs[0].target_liveness == "ended"
    assert "Never send" not in claimed.jobs[0].native_instruction
    assert claimed.jobs[0].native_instruction == native_wake_instruction("message-1")
    reported = report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="wake",
        job_id=claimed.jobs[0].job_id,
        lease_id=claimed.jobs[0].lease_id,
        result_code="accepted",
        adapter_revision="adapter-1",
        evidence={
            "duration_ms": 17,
            "surface": "codex-cli",
            "native_instruction_sha256": "forged-by-relay",
            "stderr": "secret output",
            "token": "never persist",
        },
        now="2026-08-22T12:00:10Z",
    )
    duplicate = report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="wake",
        job_id=claimed.jobs[0].job_id,
        lease_id=claimed.jobs[0].lease_id,
        result_code="accepted",
        adapter_revision="adapter-1",
        now="2026-08-22T12:00:11Z",
    )

    assert duplicate == reported
    evidence = json.loads(
        conn.execute(
            "SELECT evidence FROM session_message_attempts WHERE attempt_id=?",
            (claimed.jobs[0].job_id,),
        ).fetchone()[0]
    )
    assert evidence == {
        "duration_ms": 17,
        "native_instruction_sha256": native_wake_instruction_sha256("message-1"),
        "surface": "codex-cli",
    }
    assert (
        conn.execute(
            "SELECT adapter_revision FROM session_message_attempts WHERE attempt_id=?",
            (claimed.jobs[0].job_id,),
        ).fetchone()[0]
        == "adapter-1"
    )


def test_live_lease_blocks_a_second_job_and_expires_without_guessing() -> None:
    conn = _connection()
    _add_wake_recipient(conn)
    first = claim_relay_job(conn, _heartbeat(), wait_seconds=0, now_provider=_clock())

    second = claim_relay_job(conn, _heartbeat(), wait_seconds=0, now_provider=_clock())

    assert len(first.jobs) == 1
    assert second.jobs == ()
    assert (
        conn.execute(
            "SELECT wake_attempt_count FROM session_message_recipients"
        ).fetchone()[0]
        == 1
    )
    with pytest.raises(SessionRelayError) as late:
        report_relay_job(
            conn,
            actor_id=1,
            relay_id=RELAY_ID,
            job_kind="wake",
            job_id=first.jobs[0].job_id,
            lease_id=first.jobs[0].lease_id,
            result_code="accepted",
            now="2026-08-22T12:01:31Z",
        )
    assert late.value.code == "relay_lease_expired"
    assert settle_expired_relay_leases(conn, now="2026-08-22T12:01:31Z") == 1
    attempt = conn.execute(
        "SELECT completed_at,result_code,evidence FROM session_message_attempts"
    ).fetchone()
    assert attempt[1] == "relay_lease_expired"
    assert "relay_lease_expired" in attempt[2]


def test_launch_claim_separates_attestation_and_redacts_report() -> None:
    conn = _connection()
    add_relay(
        conn,
        relay_id=RELAY_ID,
        machine_id=MACHINE_ID,
    )
    launch = assigned_launch(
        conn,
        instructions="Sensitive launch instructions",
        key="relay-launch",
        machine_id=MACHINE_ID,
    )

    claimed = claim_relay_job(conn, _heartbeat(), wait_seconds=0, now_provider=_clock())

    assert len(claimed.jobs) == 1 and claimed.jobs[0].job_kind == "launch"
    assert "Sensitive launch instructions" not in claimed.jobs[0].native_instruction
    assert claimed.jobs[0].surface_version == "0.148.0a15"
    assert claimed.jobs[0].requested_model == "gpt-5"
    assert claimed.jobs[0].launch_attestation
    result = report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="launch",
        job_id=launch.launch_id,
        lease_id=claimed.jobs[0].lease_id,
        result_code="native_created",
        native_session_id="native-session",
        adapter_revision="adapter-1",
        evidence={"exit_code": 0, "stdout": "secret"},
        now="2026-08-22T12:00:20Z",
    )
    duplicate = report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="launch",
        job_id=launch.launch_id,
        lease_id=claimed.jobs[0].lease_id,
        result_code="native_created",
        native_session_id="native-session",
        adapter_revision="adapter-1",
        now="2026-08-22T12:00:21Z",
    )

    assert result["state"] == "awaiting_registration"
    assert duplicate == result
    evidence = conn.execute(
        "SELECT evidence FROM session_launch_attempts WHERE launch_id=?",
        (launch.launch_id,),
    ).fetchone()[0]
    assert json.loads(evidence) == {"exit_code": 0}


def test_private_versions_use_floors_and_malformed_versions_fail_closed() -> None:
    assert surface_operation_supported("claude-cli", "2.1.238", "message_idle")
    assert surface_operation_supported("claude-cli", "2.1.239", "message_idle")
    assert not surface_operation_supported("claude-cli", "2.1.237", "message_idle")
    assert not surface_operation_supported(
        "codex-cli", "not-a-version", "message_stopped"
    )
    assert wake_versions_supported(
        "codex-cli", "0.148.0a15", "0.148.0a15", "waiting", "active"
    )
    assert not wake_versions_supported(
        "codex-cli", "0.148.0a15", "0.148.0a15", "idle_timeout", "stale"
    )
    assert wake_versions_supported(
        "cursor-cli",
        "2026.08.11-e8db854",
        "2026.08.11-e8db854",
        "idle_timeout",
        "stale",
    )
