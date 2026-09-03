"""Durably ingest resident read-only hook effects in ordered batches."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from yoke_contracts.hook_driver_process import resolve_driver_process
from yoke_contracts.hook_evaluator_protocol import evaluator_telemetry_fields
from yoke_contracts.hook_runner.chain_registry import chain_for
from yoke_core.domain import db_backend
from yoke_core.domain.events import build_envelope as build_event_envelope
from yoke_core.domain.events_emit_write import _write_event
from yoke_core.domain.events_retired_name_guard import assert_event_name_not_retired
from yoke_core.domain.events_writes import check_severity_conn
from yoke_core.domain.observe_anomaly import detect_anomalies
from yoke_core.domain.observe_event_emission import (
    build_envelope as build_tool_envelope,
    insert_event,
)
from yoke_core.domain.observe_parsing import parse_hook_event
from yoke_core.domain.observe_pre import parse_pre_event
from yoke_core.hooks.capability_resolve import resolve_capability
from yoke_core.hooks.context import build_context


_TOOL_EVENTS = frozenset({"PreToolUse", "PostToolUse", "PostToolUseFailure"})
_DISPATCH_EVENT = "HookDispatchTelemetry"


class ObservationBatchError(RuntimeError):
    """A batch could not be proved durable and must be retried."""


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _event_exists(conn: Any, event_id: str) -> bool:
    row = conn.execute(
        f"SELECT 1 FROM events WHERE event_id = {_placeholder(conn)} LIMIT 1",
        (event_id,),
    ).fetchone()
    return row is not None


def _stable_event_id(observation_id: str, kind: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"https://upyoke.com/hook-observation/{observation_id}/{kind}",
        )
    )


def _observed_at(value: Any) -> str:
    if not isinstance(value, str):
        raise ObservationBatchError("observation timestamp is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ObservationBatchError("observation timestamp is invalid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _request_payload(request: Mapping[str, Any]) -> tuple[Any, dict[str, Any]]:
    executor = str(request.get("executor") or "claude")
    capability = resolve_capability(executor)
    stdin_data = request.get("stdin")
    if not isinstance(stdin_data, str):
        raise ObservationBatchError("hook request stdin must be a string")
    payload = capability.payload_parser(stdin_data) if stdin_data else {}
    if not isinstance(payload, dict):
        payload = {}
    extras = request.get("payload_extra")
    if isinstance(extras, Mapping):
        payload.update(extras)
    for field in (
        "agent_type",
        "entrypoint",
        "model",
        "reasoning_effort",
        "context_window_tokens",
        "requested_model",
        "requested_reasoning_effort",
        "requested_context_window_tokens",
        "execution_lane",
        "project_id",
        "executor_version",
        "machine_id",
        "native_thread_id",
    ):
        value = request.get(field)
        if value is not None and value != "":
            payload[field] = value
    return capability, payload


def _tool_event(
    conn: Any,
    *,
    event_name: str,
    payload: dict[str, Any],
    context: Any,
    observed_at: str,
    event_id: str,
) -> None:
    if _event_exists(conn, event_id):
        return
    if event_name == "PreToolUse":
        envelope = parse_pre_event(payload, fallback_cwd=context.cwd)
    else:
        tool_use_id = payload.get("tool_use_id")
        record = parse_hook_event(
            payload,
            session_id=context.session_id or "",
            item_id=str(context.item_id) if context.item_id is not None else None,
            agent_type=(
                str(payload.get("agent_type")) if payload.get("agent_type") else None
            ),
            hook_event=event_name,
            tool_use_id=str(tool_use_id) if tool_use_id else None,
            project_dir=context.cwd,
        )
        if record is None:
            envelope = None
        else:
            detect_anomalies(record)
            envelope = build_tool_envelope(record)
    if envelope is None:
        return
    envelope["event_id"] = event_id
    envelope["event_time"] = observed_at
    insert_event(conn, envelope)
    if not _event_exists(conn, event_id):
        raise ObservationBatchError(
            f"{envelope.get('event_name', 'tool event')} was not persisted"
        )


def _dispatch_event(
    conn: Any,
    *,
    observation_id: str,
    event_name: str,
    request: Mapping[str, Any],
    payload: dict[str, Any],
    context: Any,
    observed_at: str,
    hook_wait_ms: int,
) -> None:
    event_id = _stable_event_id(observation_id, "dispatch")
    if _event_exists(conn, event_id):
        return
    tool_name = context.tool_name or ""
    matcher = tool_name if event_name in _TOOL_EVENTS else None
    driver = resolve_driver_process(payload, hook_event=event_name)
    extra = {
        "module": "yoke_core.hooks",
        "hook_event": event_name,
        "executor": context.executor_family,
        "chain_length": len(chain_for(event_name, matcher)),
        "decision_outcome": "allow",
        "hook_wait_ms": hook_wait_ms,
        "timed_out": False,
        "total_timeout_ms": int(request.get("deadline_ms") or 0),
        "driver_pid": driver.get("pid"),
        "driver_ppid": driver.get("ppid"),
        "driver_origin": driver.get("origin"),
        **evaluator_telemetry_fields(payload),
    }
    envelope = build_event_envelope(
        _DISPATCH_EVENT,
        event_kind="system",
        event_type="hook_dispatch",
        source_type="hook",
        session_id=context.session_id or "unknown",
        severity="INFO",
        outcome="completed",
        project="yoke",
        item_id=str(context.item_id) if context.item_id is not None else None,
        tool_name=tool_name or None,
        duration_ms=hook_wait_ms,
        hook_event_name=event_name,
        context=extra,
        created_at=observed_at,
    )
    envelope["event_id"] = event_id
    assert_event_name_not_retired(conn, _DISPATCH_EVENT)
    if not check_severity_conn(conn, _DISPATCH_EVENT, "hook", "INFO"):
        return
    wrote = _write_event(envelope, conn=conn)
    if not wrote and not _event_exists(conn, event_id):
        raise ObservationBatchError("HookDispatchTelemetry was not persisted")


def _stamp_heartbeat(conn: Any, session_id: str, observed_at: str) -> None:
    if not session_id or session_id == "unknown":
        return
    marker = _placeholder(conn)
    conn.execute(
        "UPDATE harness_sessions SET last_heartbeat = "
        f"CASE WHEN last_heartbeat IS NULL OR last_heartbeat < {marker} "
        f"THEN {marker} ELSE last_heartbeat END "
        f"WHERE session_id = {marker} AND ended_at IS NULL",
        (observed_at, observed_at, session_id),
    )
    conn.execute(
        "UPDATE work_claims SET last_heartbeat = "
        f"CASE WHEN last_heartbeat IS NULL OR last_heartbeat < {marker} "
        f"THEN {marker} ELSE last_heartbeat END "
        f"WHERE session_id = {marker} AND released_at IS NULL",
        (observed_at, observed_at, session_id),
    )


def persist_observation_batch(observations: list[Mapping[str, Any]]) -> int:
    """Persist a validated batch; raise so the resident retains failed work."""
    conn = db_backend.connect()
    accepted = 0
    try:
        for observation in observations:
            observation_id = str(observation.get("observation_id") or "").strip()
            if not observation_id:
                raise ObservationBatchError("observation id is missing")
            request = observation.get("hook_request")
            if not isinstance(request, Mapping):
                raise ObservationBatchError("hook request is missing")
            event_name = str(request.get("event_name") or "")
            if event_name not in _TOOL_EVENTS:
                raise ObservationBatchError(
                    f"{event_name or 'unknown event'} is not batchable"
                )
            observed_at = _observed_at(observation.get("observed_at"))
            hook_wait_ms = max(0, int(observation.get("hook_wait_ms") or 0))
            capability, payload = _request_payload(request)
            context = build_context(
                event_name=event_name,
                capability=capability,
                payload=payload,
                remote=True,
            )
            _tool_event(
                conn,
                event_name=event_name,
                payload=payload,
                context=context,
                observed_at=observed_at,
                event_id=_stable_event_id(observation_id, "tool"),
            )
            _stamp_heartbeat(conn, context.session_id or "", observed_at)
            _dispatch_event(
                conn,
                observation_id=observation_id,
                event_name=event_name,
                request=request,
                payload=payload,
                context=context,
                observed_at=observed_at,
                hook_wait_ms=hook_wait_ms,
            )
            conn.commit()
            accepted += 1
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return accepted


__all__ = ["ObservationBatchError", "persist_observation_batch"]
