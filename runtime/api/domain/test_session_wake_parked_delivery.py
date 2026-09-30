"""Every new message can resume the same cleanly exited Claude worker."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from yoke_contracts.session_control.resume import RESUMED_RUNNING_RESULT
from yoke_core.domain import session_message_delivery as delivery
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_types import timestamp
from yoke_core.domain.session_relay_jobs import claim_wake_job
from yoke_core.domain.session_relay_types import RelayHeartbeat
from yoke_harness import session_relay_claude as claude
from yoke_harness.session_relay_native_spawn import SupervisedNative
from runtime.api.domain.test_session_message_support import (
    NATIVE_WAKE_SESSION_ID,
    NOW,
    NOW_TEXT,
    message_connection,
    park_session,
    record_process_gone,
    selector,
    stamp_activity,
)
from runtime.harness.test_session_relay_claude import CLAUDE, _allow, _context


def test_each_message_resumes_stored_native_identity_and_is_injected(monkeypatch):
    conn = message_connection()
    conn.execute(
        "UPDATE harness_sessions SET executor='claude-code',executor_surface='claude-cli',"
        "executor_version='2.1.238' WHERE session_id=?",
        (NATIVE_WAKE_SESSION_ID,),
    )
    conn.execute(
        "INSERT INTO session_relays (relay_id,actor_id,machine_id,hostname,"
        "relay_version,surface_versions,project_checkouts,first_seen_at,"
        "last_seen_at,connected_until,state) VALUES "
        "('machine:m4',10,'m4','relay','0.1.1',?,'[1]',?,?,?,'active')",
        (
            json.dumps({"claude-cli": "2.1.238"}),
            NOW_TEXT,
            NOW_TEXT,
            (NOW + timedelta(hours=1)).isoformat(),
        ),
    )
    park_session(conn)
    conn.execute(
        "UPDATE harness_sessions SET turn_posture='waiting',turn_posture_at=?",
        (NOW_TEXT,),
    )
    conn.commit()
    monkeypatch.setattr(claude, "claude_session_transcript_exists", lambda *_: True)
    heartbeat = RelayHeartbeat(
        relay_id="machine:m4",
        actor_id=10,
        machine_id="m4",
        hostname="relay",
        relay_version="0.1.1",
        surface_versions={"claude-cli": "2.1.238"},
        project_ids=(1,),
    )
    resumed = []
    for index in range(2):
        sent_at = NOW + timedelta(seconds=120 * (index + 1))
        record_process_gone(conn, when=sent_at - timedelta(seconds=1))
        message_id = send_message(
            conn,
            actor_id=10,
            sender_session_id="s1",
            selector=selector(session_ids=[NATIVE_WAKE_SESSION_ID]),
            body=f"Continue parked work {index}.",
            now=sent_at,
        )["message_id"]
        job = claim_wake_job(conn, heartbeat, now=timestamp(sent_at))
        assert job is not None and job.target_session_id == NATIVE_WAKE_SESSION_ID
        assert job.target_parked and job.target_liveness == "active"
        monkeypatch.setattr(delivery, "utc_now", lambda: sent_at + timedelta(seconds=1))

        def spawn(context, invocation):
            resumed.append(invocation.session_id)
            assert "--resume" in invocation.argv
            assert job.native_instruction in invocation.argv
            lease = delivery.lease_for_hook(
                conn,
                session_id=NATIVE_WAKE_SESSION_ID,
                hook_event="PreToolUse",
                limit=5,
            )
            assert lease and lease["messages"][0]["message_id"] == message_id
            delivery.complete_hook_lease(
                conn,
                lease_id=lease["lease_id"],
                injected=True,
                result="injected",
            )
            return SupervisedNative(
                4321,
                CLAUDE,
                "path",
                Path("/capture"),
                "nd-44444444-4444-4444-8444-444444444444",
                sent_at.isoformat(),
            )

        result = claude.run_claude_cli_adapter(
            _context(
                job_kind="wake",
                job_id=job.job_id,
                project_id=job.project_id,
                native_instruction=job.native_instruction,
                message_id=job.message_id,
                target_session_id=job.target_session_id,
                launch_attestation=None,
                target_liveness=job.target_liveness,
                wake_mode=job.wake_mode.value,
            ),
            executable_finder=lambda _: CLAUDE,
            version_gate=_allow,
            wake_spawner=spawn,
        )
        assert result.result_code == RESUMED_RUNNING_RESULT
        conn.execute(
            "UPDATE session_message_attempts SET completed_at=?,result_code='wake_delivered' "
            "WHERE attempt_id=?",
            (sent_at.isoformat(), job.job_id),
        )
        stamp_activity(
            conn,
            when=sent_at + timedelta(seconds=2),
            tool_call=(sent_at + timedelta(seconds=2)).isoformat(),
        )
        receipt = conn.execute(
            "SELECT state,injection_count FROM session_message_recipients "
            "WHERE message_id=?",
            (message_id,),
        ).fetchone()
        assert tuple(receipt) == ("injected", 1)
    assert resumed == [NATIVE_WAKE_SESSION_ID, NATIVE_WAKE_SESSION_ID]
