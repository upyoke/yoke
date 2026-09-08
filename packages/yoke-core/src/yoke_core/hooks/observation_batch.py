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
from yoke_core.domain.hook_observation_db_session import (
    apply_hook_observation_statement_timeout,
)
from yoke_core.domain.observe_anomaly import detect_anomalies
from yoke_core.domain.observe_event_emission import (
    build_envelope as build_tool_envelope,
    insert_event,
)
from yoke_core.domain.observe_parsing import parse_hook_event
from yoke_core.domain.observe_pre import parse_pre_event
from yoke_core.domain.observe_timing import ElapsedMeasurement, measure_elapsed
from yoke_core.hooks.capability_resolve import resolve_capability
from yoke_core.hooks.context import build_context
from yoke_core.hooks.session_model_attestation_write import confirmed_served_model


_TOOL_EVENTS = frozenset({"PreToolUse", "PostToolUse", "PostToolUseFailure"})
_DISPATCH_EVENT = "HookDispatchTelemetry"


class ObservationBatchError(RuntimeError):
    """A batch could not be proved durable and must be retried."""


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


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


def _annotate_ingest_lag(
    envelope: dict[str, Any], ingest_lag: ElapsedMeasurement
) -> None:
    """Record how long this observation waited between capture and ingest.

    The resident answers read-only hooks locally and delivers their
    observations in bounded batches afterwards, so a healthy call is
    recorded seconds after it finished. Carrying that delay beside the
    duration is what keeps deliberate batching distinguishable from a slow
    tool — without it, the only visible number is the one that moved.
    """
    context = envelope.get("context")
    if not isinstance(context, dict):
        context = {}
        envelope["context"] = context
    detail = context.get("detail")
    if not isinstance(detail, dict):
        detail = {}
        context["detail"] = detail
    detail["ingest_lag_ms"] = ingest_lag.milliseconds
    detail["ingest_lag_status"] = ingest_lag.status


def _tool_event(
    conn: Any,
    *,
    event_name: str,
    payload: dict[str, Any],
    context: Any,
    observed_at: str,
    event_id: str,
    ingest_lag: ElapsedMeasurement,
) -> None:
    """Apply one observation to session state and record its telemetry.

    Deliberately unguarded by whether the telemetry row already exists.
    A stable event id used to short-circuit this function, which made two
    unrelated things true at once: a replay was skipped, *and* it was
    skipped only for as long as the ``events`` row survived. Once that row
    expired the same replay reapplied the state it had already applied.
    The state writes are idempotent on the call identity instead, so
    replaying is safe whether or not telemetry still remembers it.
    """
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
            completed_at=observed_at,
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
    _annotate_ingest_lag(envelope, ingest_lag)
    insert_event(conn, envelope)


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
    # Best-effort: this envelope is pure hook-dispatch telemetry with no
    # state behind it, and a severity filter or a dropped write is a
    # deployment's own choice about what it retains. Failing the batch
    # here would make the observation's state write hostage to it.
    _write_event(envelope, conn=conn)


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


def _refresh_session_identity(
    conn: Any,
    *,
    payload: dict[str, Any],
    context: Any,
    actor_id: int,
) -> None:
    """Apply wire identity through the ordinary active-session healing path."""
    from yoke_core.hooks.registration import ensure_registered_from_hook

    transcript = payload.get("transcript_path")
    ensure_registered_from_hook(
        conn,
        json.dumps(payload),
        context.session_id or "",
        transcript_path=transcript if isinstance(transcript, str) else "",
        record_anchor=False,
        executor_hint=context.executor_family or "",
        register_in_process=True,
        actor_id=actor_id,
        project_id=payload.get("project_id"),
    )


def persist_observation_batch(
    observations: list[Mapping[str, Any]], *, actor_id: int
) -> tuple[int, dict[str, str]]:
    """Persist a validated batch; raise so the resident retains failed work."""
    conn = db_backend.connect()
    accepted = 0
    model_confirmations: dict[str, str] = {}
    try:
        apply_hook_observation_statement_timeout(conn)
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
            _refresh_session_identity(
                conn, payload=payload, context=context, actor_id=actor_id
            )
            _tool_event(
                conn,
                event_name=event_name,
                payload=payload,
                context=context,
                observed_at=observed_at,
                event_id=_stable_event_id(observation_id, "tool"),
                ingest_lag=measure_elapsed(observed_at, datetime.now(timezone.utc)),
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
            confirmed = confirmed_served_model(
                context.session_id, request.get("model"), conn=conn
            )
            if confirmed is not None:
                model_confirmations[observation_id] = confirmed
            accepted += 1
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return accepted, model_confirmations


__all__ = ["ObservationBatchError", "persist_observation_batch"]
