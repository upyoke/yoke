# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.handlers.sessions_list import handle_sessions_list

from yoke_core.domain.session_control_roster import SESSION_CONTROL_ROSTER_FIELDS

from yoke_core.domain.session_control_schema import create_session_control_tables

from yoke_core.domain.sessions_list_read import LIVENESS_STATES, list_sessions

from yoke_core.domain.work_claim_targets import (
    make_epic_task_target,
    make_item_target,
    make_process_target,
)

from yoke_core.domain.work_processes import PROCESS_FEED


def _iso(minutes_ago: int = 0) -> str:
    stamp = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


_LONG_AGO_MINUTES = 60 * 24 * 30


def _request(payload: dict | None = None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="sessions.list",
        actor=ActorContext(actor_id=None, session_id=""),
        target=TargetRef(kind="global"),
        payload={"detail": "full", **(payload or {})},
    )


def _insert_session(
    conn,
    session_id: str,
    *,
    last_heartbeat: str,
    offered_at: str | None = None,
    last_tool_call_at: str | None = None,
    ended_at: str | None = None,
    terminated_at: str | None = None,
    executor: str = "claude-code",
    level: str = "primary",
    mode: str = "wait",
    project_id: int = 1,
    actor_id: int | None = None,
    current_item_id: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO harness_sessions ("
        "session_id, executor, provider, model, execution_level, workspace, "
        "project_id, mode, offered_at, last_heartbeat, last_tool_call_at, "
        "ended_at, terminated_at, actor_id, current_item_id"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            session_id,
            executor,
            "anthropic",
            "test-model",
            level,
            "/tmp/workspace",
            project_id,
            mode,
            offered_at or last_heartbeat,
            last_heartbeat,
            last_tool_call_at,
            ended_at,
            terminated_at,
            actor_id,
            current_item_id,
        ),
    )
    conn.commit()


def _insert_item_claim(conn, session_id: str, item_id: int) -> None:
    target = make_item_target(item_id)
    conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, scope, claimed_at, last_heartbeat, reason) VALUES (%s, %s, %s, %s, %s, %s)",
        (
            session_id,
            target.kind,
            target.scope_json(),
            _iso(),
            _iso(),
            "implementation",
        ),
    )
    conn.commit()
