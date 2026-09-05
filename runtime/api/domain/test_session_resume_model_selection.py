"""Current model selection carried by direct and broker wake jobs."""

from __future__ import annotations

from datetime import timedelta

import pytest

from yoke_core.domain.session_broker_wake import lease_broker_wake_for_hook
from yoke_core.domain.session_broker_wake_settlement import (
    complete_broker_hook_lease,
)
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_relay import claim_relay_job
from yoke_core.domain.session_relay_types import RelayHeartbeat
from runtime.api.domain.test_session_message_support import (
    NOW,
    NOW_TEXT,
    message_connection,
    selector,
)


MACHINE_ID = "11111111-1111-4111-8111-111111111111"
RELAY_ID = f"machine:{MACHINE_ID}"


def _stamp(*, minutes: int = 0, seconds: int = 0) -> str:
    value = NOW + timedelta(minutes=minutes, seconds=seconds)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _heartbeat() -> RelayHeartbeat:
    return RelayHeartbeat(
        relay_id=RELAY_ID,
        actor_id=10,
        machine_id=MACHINE_ID,
        hostname="wake-host",
        relay_version="0.1.1",
        surface_versions={"codex-cli": "0.148.0a15"},
        project_ids=(1,),
        preferred_session_models={"codex-cli": "gpt-6-astra"},
        preferred_session_reasoning_efforts={"codex-cli": "max"},
    )


def _seed_target(*, broker: bool, served: tuple, requested: tuple):
    conn = message_connection()
    idle_at = _stamp(minutes=-11)
    conn.execute(
        "UPDATE harness_sessions SET machine_id=?,ended_at=?,last_heartbeat=?,"
        "last_tool_call_at=?,turn_posture='unknown',turn_posture_at=?,"
        "native_thread_id='current-thread',model=?,reasoning_effort=?,"
        "context_window_tokens=?,requested_model=?,"
        "requested_reasoning_effort=?,requested_context_window_tokens=? "
        "WHERE session_id='s4'",
        (
            MACHINE_ID,
            NOW_TEXT,
            idle_at,
            idle_at,
            NOW_TEXT,
            *served,
            *requested,
        ),
    )
    if broker:
        conn.execute(
            "INSERT INTO harness_sessions "
            "(session_id,project_id,executor,executor_surface,executor_version,"
            "machine_id,execution_lane,last_heartbeat,last_tool_call_at,offered_at,"
            "turn_posture,turn_posture_at) VALUES "
            "('broker',1,'codex','codex-desktop','26.818.31338',?,'direct',"
            "?,?,?,'running',?)",
            (MACHINE_ID, NOW_TEXT, NOW_TEXT, NOW_TEXT, NOW_TEXT),
        )
    conn.commit()
    send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=["s4"]),
        body="check current selection",
        now=NOW - timedelta(minutes=11),
    )
    return conn


def _claim(*, route: str, served: tuple, requested: tuple):
    broker = route == "broker"
    conn = _seed_target(broker=broker, served=served, requested=requested)
    options = {}
    if broker:
        lease = lease_broker_wake_for_hook(
            conn,
            broker_session_id="broker",
            hook_event="PreToolUse",
            now=NOW + timedelta(seconds=1),
        )
        assert lease is not None
        complete_broker_hook_lease(
            conn,
            lease_id=lease.lease_id,
            delivered=True,
            result="injected",
            now=NOW + timedelta(seconds=2),
        )
        options = {
            "broker_only": True,
            "broker_lease_id": lease.lease_id,
            "broker_session_id": "broker",
        }
    outcome = claim_relay_job(
        conn,
        _heartbeat(),
        wait_seconds=0,
        now_provider=lambda: _stamp(seconds=3),
        **options,
    )
    assert len(outcome.jobs) == 1
    return outcome.jobs[0]


@pytest.mark.parametrize("route", ["direct", "broker"])
def test_wake_replays_later_attested_selection_not_launch_or_machine(route) -> None:
    job = _claim(
        route=route,
        served=("gpt-5.6-sol", "xhigh", 258_400),
        requested=("gpt-5.5", "medium", 1_000_000),
    )

    assert job.requested_model == "gpt-5.6-sol"
    assert job.requested_reasoning_effort == "xhigh"
    assert job.requested_context_window_tokens is None
    assert job.target_session_id == "s4"
    assert job.target_native_thread_id == "current-thread"


@pytest.mark.parametrize("route", ["direct", "broker"])
def test_wake_uses_launch_request_only_before_provider_attestation(route) -> None:
    job = _claim(
        route=route,
        served=(None, None, None),
        requested=("gpt-5.5", "medium", 1_000_000),
    )

    assert job.requested_model == "gpt-5.5"
    assert job.requested_reasoning_effort == "medium"
    assert job.requested_context_window_tokens is None


def test_partial_attestation_does_not_backfill_old_or_unsupported_knobs() -> None:
    job = _claim(
        route="direct",
        served=(None, None, 258_400),
        requested=("gpt-5.5", "medium", 1_000_000),
    )

    assert job.requested_model is None
    assert job.requested_reasoning_effort is None
    assert job.requested_context_window_tokens is None
