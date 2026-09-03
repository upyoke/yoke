"""Shared scope seeding for the steering fleet report's tests.

Composition, rendering, and the detectors are three test modules reading
one fleet, so the sessions, relay, and steering claim that make up that
fleet are seeded here once rather than copied into each of them.
"""

from __future__ import annotations

import json

from runtime.api.fixtures.backlog import insert_item
from yoke_contracts.session_control.plan_limits import ALL_MODELS_SCOPE
from yoke_core.domain.steering_claims import acquire as acquire_steering
from yoke_core.domain.steering_fleet_report import ClaimHolder, compose_report
from yoke_core.domain.steering_fleet_report_limits import MachinePlanLimit
from yoke_core.domain.strategy_docs_defaults import seed_default_docs


NOW = "2026-08-26T12:00:00Z"
LONG_AGO = "2026-08-26T09:00:00Z"
BEFORE_THAT = "2026-08-26T08:00:00Z"
JUST_NOW = "2026-08-26T11:58:00Z"
STAFFING_SECONDS = 5 * 60
IDLE_SECONDS = 20 * 60
SURFACE = "codex-cli"
STEERING_SESSION = "steering-holder"
WORKER_SESSION = "another-worker"
ASKER = "asking-worker"
ANSWERER = "answering-worker"
PROJECT_ID = 1
PLAN_LIMIT_HOST = "beebauman-macbook-pro-16"
ACTOR_ID = 2


def seed_session(conn, session_id: str, **columns) -> None:
    """One live session, defaulting to an ordinary idle worker."""
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, model, execution_lane, workspace, "
        "project_id, mode, offered_at, last_heartbeat, actor_id, "
        "executor_surface, machine_id, last_tool_call_at, ended_at, "
        "terminated_at, current_item_id) "
        "VALUES (%s, %s, 'openai', 'test-model', 'primary', %s, %s, "
        "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            session_id,
            columns.get("executor", "codex"),
            f"/tmp/{session_id}",
            PROJECT_ID,
            columns.get("mode", "wait"),
            NOW,
            NOW,
            ACTOR_ID,
            columns.get("executor_surface", SURFACE),
            columns.get("machine_id", "machine-1"),
            columns.get("last_tool_call_at"),
            columns.get("ended_at"),
            columns.get("terminated_at"),
            columns.get("current_item_id"),
        ),
    )


def seed_tool_call(
    conn,
    session_id: str,
    *,
    tool_use_id: str,
    started_at: str,
    command_summary: str,
    completed_at: str | None = None,
    tool_name: str = "Bash",
) -> None:
    """One ``session_tool_calls`` row, open unless ``completed_at`` is given."""
    conn.execute(
        "INSERT INTO session_tool_calls "
        "(session_id, tool_use_id, tool_name, started_at, completed_at, "
        "command_summary) VALUES (%s, %s, %s, %s, %s, %s)",
        (
            session_id,
            tool_use_id,
            tool_name,
            started_at,
            completed_at,
            command_summary,
        ),
    )


def seed_denial(conn, session_id: str, *, tool_use_id: str, at: str) -> None:
    """The PreToolUse guardrail event that marks a start row as refused."""
    conn.execute(
        "INSERT INTO events "
        "(event_id, source_type, session_id, event_kind, event_type, "
        "event_name, tool_name, tool_use_id, created_at) "
        "VALUES (%s, 'hook', %s, 'audit', 'tool_call', "
        "'HarnessToolCallDenied', 'Bash', %s, %s)",
        (f"denial-{tool_use_id}", session_id, tool_use_id, at),
    )


def seed_relay(conn) -> None:
    """One connected relay, so a launch has somewhere it could land."""
    conn.execute(
        "INSERT INTO session_relays "
        "(relay_id, actor_id, machine_id, hostname, surface_versions, "
        "project_checkouts, first_seen_at, last_seen_at, connected_until, state) "
        "VALUES ('relay-1', %s, 'machine-1', 'relay-host', %s, %s, %s, %s, "
        "%s, 'active')",
        (
            ACTOR_ID,
            json.dumps({SURFACE: "0.148.0a15"}),
            json.dumps([PROJECT_ID]),
            NOW,
            NOW,
            "2026-08-26T23:00:00Z",
        ),
    )


def compose(conn, session_id: str = STEERING_SESSION, now: str = NOW):
    """One report at the project's default thresholds."""
    return compose_report(
        conn,
        project_id=PROJECT_ID,
        session_id=session_id,
        staffing_after_seconds=STAFFING_SECONDS,
        idle_after_seconds=IDLE_SECONDS,
        now=now,
    )


def quiet_holder(session_id: str, item_id: int = 1) -> ClaimHolder:
    """A holder that has said nothing for three hours."""
    return ClaimHolder(
        session_id=session_id,
        item_id=item_id,
        public_ref=f"YOK-{item_id}",
        mode="wait",
        parked=False,
        last_activity_at=LONG_AGO,
        idle_seconds=3 * 3600,
    )


def seed_steering_scope(conn):
    """A steering holder, a connected relay, and three long-unpicked items.

    A plain function rather than a fixture: a fixture imported by name
    reads as a redefinition at every test that takes it, so each module
    wraps this in its own three-line fixture instead.
    """
    seed_session(conn, STEERING_SESSION)
    seed_session(conn, WORKER_SESSION, last_tool_call_at=LONG_AGO)
    seed_relay(conn)
    for item_id in (1, 2, 3):
        insert_item(
            conn,
            id=item_id,
            title=f"Unpicked work {item_id}",
            status="idea",
            created_at=LONG_AGO,
            updated_at=LONG_AGO,
            spec=f"# Unpicked work {item_id}\n\nA real spec body.",
        )
    conn.commit()
    seed_default_docs(conn, PROJECT_ID, "Yoke")
    acquire_steering(
        conn,
        session_id=STEERING_SESSION,
        project_id=PROJECT_ID,
        reason="steering",
    )
    return conn


def plan_limit_row(
    *,
    machine_id: str = "machine-1",
    hostname: str = PLAN_LIMIT_HOST,
    surface: str = "cursor-cli",
    plan_tier: str | None = "Ultra",
    window_kind: str = "monthly",
    scope: str = ALL_MODELS_SCOPE,
    remaining_percent: float | None = 22.0,
    resets_at: str | None = "2026-09-07T01:00:00Z",
    status: str = "ok",
    reason: str | None = None,
) -> MachinePlanLimit:
    """One (machine, surface, window) meter for the report renderers."""
    return MachinePlanLimit(
        machine_id=machine_id,
        hostname=hostname,
        surface=surface,
        plan_tier=plan_tier,
        window_kind=window_kind,
        scope=scope,
        remaining_percent=remaining_percent,
        resets_at=resets_at,
        status=status,
        reason=reason,
    )


__all__ = [
    "ACTOR_ID",
    "ANSWERER",
    "ASKER",
    "BEFORE_THAT",
    "IDLE_SECONDS",
    "JUST_NOW",
    "LONG_AGO",
    "NOW",
    "PLAN_LIMIT_HOST",
    "PROJECT_ID",
    "STAFFING_SECONDS",
    "STEERING_SESSION",
    "SURFACE",
    "WORKER_SESSION",
    "compose",
    "plan_limit_row",
    "quiet_holder",
    "seed_denial",
    "seed_relay",
    "seed_session",
    "seed_steering_scope",
    "seed_tool_call",
]
