"""Exact broker adoption through Claude resume and private diagnostics."""

from __future__ import annotations

import json
from types import SimpleNamespace

from runtime.api.domain.test_session_broker_wake import (
    MACHINE_ID,
    NOW,
    _reserve,
    _seed,
    _stamp,
)
from yoke_core.domain.session_broker_wake_settlement import (
    complete_broker_hook_lease,
)
from yoke_core.domain.session_relay import claim_relay_job, report_relay_job
from yoke_core.domain.session_relay_types import RelayHeartbeat
from yoke_harness import session_relay
from yoke_harness import session_relay_claude as claude_module
from yoke_harness import session_relay_runtime as relay_runtime
from yoke_harness.session_relay_claude import (
    ClaudeProcessResult,
    run_claude_cli_adapter,
)
from yoke_harness.session_relay_inventory import RelayInventory
from yoke_harness.session_relay_native_diagnostics import read_native_diagnostic


CLAUDE_VERSION = "2.1.238"
NATIVE_STDOUT = b"private native stdout"
NATIVE_STDERR = b"private native stderr"


def _heartbeat() -> RelayHeartbeat:
    return RelayHeartbeat(
        relay_id=f"machine:{MACHINE_ID}",
        actor_id=10,
        machine_id=MACHINE_ID,
        hostname="broker-host",
        relay_version="0.1.1",
        surface_versions={"claude-cli": CLAUDE_VERSION},
        project_ids=(1,),
    )


def _inventory() -> RelayInventory:
    heartbeat = _heartbeat()
    return RelayInventory(
        relay_id=heartbeat.relay_id,
        machine_id=heartbeat.machine_id,
        hostname=heartbeat.hostname,
        relay_version=heartbeat.relay_version,
        project_ids=tuple(heartbeat.project_ids),
        surface_versions=dict(heartbeat.surface_versions),
    )


def test_exact_broker_lease_resumes_claude_and_reports_private_diagnostic(
    monkeypatch,
    tmp_path,
) -> None:
    conn, message_id = _seed()
    conn.execute(
        "UPDATE harness_sessions SET executor='claude-code',"
        "executor_surface='claude-cli',executor_version=? WHERE session_id='s4'",
        (CLAUDE_VERSION,),
    )
    conn.execute(
        "UPDATE session_message_recipients SET executor_surface='claude-cli',"
        "executor_version=? WHERE session_id='s4'",
        (CLAUDE_VERSION,),
    )
    conn.commit()
    lease = _reserve(conn)
    assert lease is not None
    complete_broker_hook_lease(
        conn,
        lease_id=lease.lease_id,
        delivered=True,
        result="injected",
        now=NOW.replace(second=2),
    )

    contexts = []
    invocations = []
    reports = []
    monkeypatch.setattr(relay_runtime, "_ADAPTERS", {})
    monkeypatch.setattr(relay_runtime, "_checkout_for_project", lambda _id: tmp_path)
    monkeypatch.setattr(
        claude_module,
        "claude_session_transcript_exists",
        lambda checkout, session_id: True,
    )

    def claude_adapter(context):
        contexts.append(context)
        return run_claude_cli_adapter(
            context,
            process_runner=lambda invocation: (
                invocations.append(invocation)
                or ClaudeProcessResult(
                    9,
                    12,
                    stdout_bytes=NATIVE_STDOUT,
                    stderr_bytes=NATIVE_STDERR,
                )
            ),
            executable_finder=lambda _name: "/opt/claude/bin/claude",
        )

    relay_runtime.register_relay_adapter("claude-cli", claude_adapter)

    def dispatch(**kwargs):
        payload = kwargs["payload"]
        if kwargs["function_id"] == session_relay.RELAY_CLAIM_FUNCTION_ID:
            assert payload["broker_lease_id"] == lease.lease_id
            claimed = claim_relay_job(
                conn,
                _heartbeat(),
                wait_seconds=payload["wait_seconds"],
                broker_only=payload["broker_only"],
                broker_lease_id=payload["broker_lease_id"],
                broker_session_id="broker-a",
                now_provider=lambda: _stamp(seconds=3),
            )
            return SimpleNamespace(success=True, result=claimed.to_dict())
        reports.append(payload)
        result = report_relay_job(
            conn,
            actor_id=10,
            relay_id=str(payload["relay_id"]),
            job_kind=str(payload["job_kind"]),
            job_id=str(payload["job_id"]),
            lease_id=str(payload["lease_id"]),
            result_code=str(payload["result"]),
            adapter_revision=str(payload["adapter_revision"]),
            evidence=payload["evidence"],
            now=_stamp(seconds=4),
        )
        return SimpleNamespace(success=True, result=result)

    outcome = session_relay.serve_once(
        state_dir=tmp_path,
        inventory_provider=_inventory,
        dispatcher=dispatch,
        clock=lambda: 1000.0,
        broker_only=True,
        broker_lease_id=lease.lease_id,
    )

    assert outcome.state == "reported"
    assert outcome.result_code == "failed"
    assert contexts[0].lease_id == lease.lease_id
    assert contexts[0].wake_route == "broker"
    assert contexts[0].target_session_id == "s4"
    assert invocations[0].argv[:4] == (
        "/opt/claude/bin/claude",
        "-p",
        "--resume",
        "s4",
    )
    assert message_id in invocations[0].instruction
    assert lease.lease_id not in repr(invocations[0])

    evidence = reports[0]["evidence"]
    reference = evidence["native_diagnostic_ref"]
    assert reference == outcome.native_diagnostic_ref
    assert evidence["native_error_step"] == "resume"
    assert NATIVE_STDOUT.decode() not in repr(reports[0])
    assert NATIVE_STDERR.decode() not in repr(reports[0])
    retained = read_native_diagnostic(reference, state_dir=tmp_path, now=1001)
    assert NATIVE_STDOUT in retained
    assert NATIVE_STDERR in retained

    row = conn.execute(
        "SELECT result_code,evidence FROM session_message_attempts WHERE attempt_id=?",
        (lease.attempt_id,),
    ).fetchone()
    assert row[0] == "failed"
    assert json.loads(row[1])["native_diagnostic_ref"] == reference
