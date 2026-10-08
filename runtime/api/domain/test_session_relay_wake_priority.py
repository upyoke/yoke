"""Pending worker mail leads a batch that also admits queued launches."""

from __future__ import annotations

import pytest

from yoke_contracts.session_control.wake_delivery import NATIVE_RESUME_ACCEPTED_RESULT
from yoke_core.domain import session_message_delivery as delivery
from yoke_core.domain.session_message_types import parse_timestamp
from yoke_core.domain.session_relay import claim_relay_job, report_relay_job
from yoke_core.domain.session_relay_types import RelayHeartbeat, WakeMode
from runtime.api.domain.session_launch_test_support import add_relay, assigned_launch
from runtime.api.domain.test_session_message_support import park_session
from runtime.api.domain.test_session_relay import (
    MACHINE_ID,
    NOW,
    RELAY_ID,
    _add_wake_recipient,
    _connection,
)


@pytest.mark.parametrize(
    ("executor", "surface", "version"),
    [
        ("codex", "codex-cli", "0.148.0a15"),
        ("claude-code", "claude-cli", "2.1.238"),
        ("cursor", "cursor-cli", "2026.08.11"),
    ],
)
def test_parked_worker_receives_mail_before_new_launches(
    monkeypatch, executor, surface, version
) -> None:
    conn = _connection()
    add_relay(
        conn,
        relay_id=RELAY_ID,
        machine_id=MACHINE_ID,
        surface=surface,
        version=version,
    )
    # New creates remain available on this machine throughout the delivery.
    launches = [
        assigned_launch(
            conn,
            key=f"queued-create-{index}",
            machine_id=MACHINE_ID,
            surface=surface,
            model=None,
        ).launch_id
        for index in range(3)
    ]
    _add_wake_recipient(conn)
    conn.execute(
        "UPDATE harness_sessions SET executor=?,executor_surface=?,"
        "executor_version=?,ended_at=NULL WHERE session_id='target'",
        (executor, surface, version),
    )
    conn.execute(
        "UPDATE session_message_recipients SET executor_surface=?,executor_version=?",
        (surface, version),
    )
    park_session(conn, session_id="target")
    heartbeat = RelayHeartbeat(
        relay_id=RELAY_ID,
        machine_id=MACHINE_ID,
        actor_id=1,
        hostname="relay-host",
        relay_version="0.1.1",
        surface_versions={surface: version},
        project_ids=(10,),
    )

    outcome = claim_relay_job(
        conn,
        heartbeat,
        wait_seconds=0,
        now_provider=lambda: NOW,
    )

    assert len(outcome.jobs) == 1 + len(launches)
    wake = outcome.jobs[0]
    assert wake.job_kind == "wake" and wake.target_session_id == "target"
    assert wake.target_parked and wake.wake_mode is WakeMode.WAITING
    assert [job.job_kind for job in outcome.jobs[1:]] == ["launch"] * len(launches)
    assert {job.job_id for job in outcome.jobs[1:]} == set(launches)
    assert conn.execute("SELECT COUNT(*) FROM session_launch_attempts").fetchone()[
        0
    ] == len(launches)
    # No explicit wake request: the queued message alone caused this resume,
    # whose first hook delivers the original body to the same worker.
    monkeypatch.setattr(delivery, "utc_now", lambda: parse_timestamp(NOW))
    lease = delivery.lease_for_hook(
        conn,
        session_id="target",
        hook_event="PostToolUse",
        limit=5,
    )
    assert lease and lease["messages"][0]["message_id"] == wake.message_id
    delivery.complete_hook_lease(
        conn,
        lease_id=lease["lease_id"],
        injected=True,
        result="injected",
    )
    report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="wake",
        job_id=wake.job_id,
        lease_id=wake.lease_id,
        result_code=NATIVE_RESUME_ACCEPTED_RESULT,
        now=NOW,
    )
    receipt = conn.execute(
        "SELECT state,injection_count FROM session_message_recipients "
        "WHERE message_id=?",
        (wake.message_id,),
    ).fetchone()
    assert tuple(receipt) == ("injected", 1)

    # Every create is already leased, even before the wake report settles.
    following = claim_relay_job(
        conn,
        heartbeat,
        wait_seconds=0,
        now_provider=lambda: NOW,
    )
    assert following.jobs == ()
