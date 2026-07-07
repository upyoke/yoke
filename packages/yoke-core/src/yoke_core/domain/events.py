"""Native Python event emitter for the Yoke event platform.

Writes directly to the ``events`` table, preserving the canonical envelope
and indexed columns from ``docs/event-contract.md`` for Python-owned
telemetry. Event emission is non-fatal — failures are logged at DEBUG and
swallowed so they never crash frontier computation, schedule computation,
session offering, or next-action selection. The emitter resolves
the DB path via :func:`yoke_core.domain.db_helpers.resolve_db_path`.

Envelope, emitter, and INSERT owner; sibling isolation/argv helpers re-export here.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from . import db_backend
from .auth_context import StandardAuthContext, merge_context
from .events_crud import decompose_work_unit, normalize_event_item_id, normalize_severity
from .events_envelope_shrink import fit_envelope_context
from .events_isolation import (
    SYNTHETIC_SMOKE_FLAG,
    _anomaly_flags_contain,
    _resolve_db_path,
    isolation_gate_blocks,
)
from .events_project_identity import (
    resolve_envelope_project_id_for_event,
    resolve_item_id_for_event,
)
from .events_retired_name_guard import RetiredEventNameError, assert_event_name_not_retired
from .events_session_actor import apply_session_actor_id
from .events_insert_sql import _INSERT_SQL
from .events_trace import current_trace_context
from .events_writes import check_severity, check_severity_conn
from .events_write_conn import event_insert_params, write_event_row_on_conn

logger = logging.getLogger(__name__)

MAX_ENVELOPE_BYTES = 65536
MAX_CONTEXT_FIELD_BYTES = 2048


@dataclass(frozen=True)
class EmitResult:
    """Structured outcome for best-effort event emission."""

    ok: bool
    event_id: Optional[str] = None
    reason: str = ""
    envelope: Optional[Dict[str, Any]] = None

    def get(self, key: str, default: Any = None) -> Any:
        if self.envelope is None:
            return default
        return self.envelope.get(key, default)

    def __getitem__(self, key: str) -> Any:
        if self.envelope is None:
            raise KeyError(key)
        return self.envelope[key]


def build_envelope(
    event_name: str,
    *,
    event_kind: str,
    event_type: str,
    source_type: str = "backend",
    session_id: str = "",
    severity: str = "INFO",
    outcome: Optional[str] = "completed",
    user_id: Optional[str] = None,
    org_id: Optional[str] = None,
    environment: Optional[str] = None,
    request_id: Optional[str] = None,
    project: str = "yoke",
    item_id: Optional[str] = None,
    task_num: Optional[int] = None,
    agent: Optional[str] = None,
    tool_name: Optional[str] = None,
    duration_ms: Optional[int] = None,
    exit_code: Optional[int] = None,
    trace_id: Optional[str] = None,
    parent_id: Optional[str] = None,
    anomaly_flags: Optional[str] = None,
    tool_use_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    hook_event_name: Optional[str] = None,
    auth_context: Optional[StandardAuthContext] = None,
    context: Optional[Dict[str, Any]] = None,
    created_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the canonical event envelope stored in ``events.envelope``."""
    # Reject unknown / normalize known; severity_num still defaults at read-side.
    severity = normalize_severity(severity)

    event_id = str(uuid.uuid4())
    if created_at is None:
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Enforce context field size limits
    safe_context: Dict[str, Any] = {}
    for key, value in merge_context(context, auth_context).items():
        if isinstance(value, str) and len(value) > MAX_CONTEXT_FIELD_BYTES:
            safe_context[key] = value[:MAX_CONTEXT_FIELD_BYTES]
        else:
            safe_context[key] = value

    # Keep machine-readable item references canonical inside structured context
    # too, so emitters cannot drift even if they pass legacy-looking values.
    if "item_id" in safe_context:
        safe_context["item_id"] = normalize_event_item_id(safe_context.get("item_id"))
    detail = safe_context.get("detail")
    if isinstance(detail, dict) and "item_id" in detail:
        detail = dict(detail)
        detail["item_id"] = normalize_event_item_id(detail.get("item_id"))
        safe_context["detail"] = detail

    # Decompose composite / sentinel work-unit identifiers so the indexed
    # item_id column stays bare-numeric. epic-N-task-M splits cleanly;
    # lane sentinels (STRATEGIZE, DOCTOR, run-*) surface in context.work_unit.
    decomposed_item, decomposed_task, work_unit_sentinel = decompose_work_unit(item_id)
    if decomposed_task is not None and task_num is None:
        task_num = decomposed_task
    if work_unit_sentinel is not None and "work_unit" not in safe_context:
        safe_context["work_unit"] = work_unit_sentinel

    active_trace = current_trace_context()
    trace_id = trace_id or active_trace.get("trace_id")
    span_id = active_trace.get("span_id")

    envelope: Dict[str, Any] = {
        "event_id": event_id,
        "event_name": event_name,
        "event_kind": event_kind,
        "event_type": event_type,
        "source_type": source_type,
        "session_id": session_id,
        "user_id": user_id,
        "org_id": org_id,
        "actor_id": auth_context.actor_id if auth_context else None,
        "environment": environment,
        "severity": severity,
        "event_outcome": outcome,
        "service": "cli",
        "project": project,
        "request_id": request_id,
        "item_id": decomposed_item,
        "task_num": task_num,
        "agent": agent,
        "tool_name": tool_name,
        "duration_ms": duration_ms,
        "exit_code": exit_code,
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_id": parent_id,
        "anomaly_flags": anomaly_flags,
        "tool_use_id": tool_use_id,
        "turn_id": turn_id,
        "hook_event_name": hook_event_name,
        "created_at": created_at,
        "context": safe_context,
    }

    # Enforce total envelope size — value-aware: oversized context values
    # become per-value markers; identity scalars (function, request_id,
    # counts) survive so audits and idempotency-replay detection keep
    # working for big-result calls.
    fit_envelope_context(envelope, max_envelope_bytes=MAX_ENVELOPE_BYTES)

    return envelope


def emit_event(
    event_name: str,
    *,
    event_kind: str,
    event_type: str,
    source_type: str = "backend",
    session_id: str = "",
    severity: str = "INFO",
    outcome: Optional[str] = "completed",
    user_id: Optional[str] = None,
    org_id: Optional[str] = None,
    environment: Optional[str] = None,
    request_id: Optional[str] = None,
    project: str = "yoke",
    item_id: Optional[str] = None,
    task_num: Optional[int] = None,
    agent: Optional[str] = None,
    tool_name: Optional[str] = None,
    duration_ms: Optional[int] = None,
    exit_code: Optional[int] = None,
    trace_id: Optional[str] = None,
    parent_id: Optional[str] = None,
    anomaly_flags: Optional[str] = None,
    tool_use_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    hook_event_name: Optional[str] = None,
    auth_context: Optional[StandardAuthContext] = None,
    context: Optional[Dict[str, Any]] = None,
    created_at: Optional[str] = None,
    db_path: Optional[str] = None,
    conn: Optional[Any] = None,
) -> EmitResult:
    """Emit a structured event to the events table (non-fatal).

    Builds the canonical envelope, honors ``YOKE_EVENTS_CAPTURE``, runs
    isolation + severity gates, and inserts into ``events``. Returns an
    :class:`EmitResult` so callers can distinguish refusal, missing schema,
    ``severity_filtered`` drops, and other exceptions.

    See ``docs/event-contract.md`` for canonical field semantics.
    Pass ``db_path`` to override the DB target (testing); pass ``conn``
    when the caller manages the connection lifecycle.
    """
    try:
        resolved_item_id = resolve_item_id_for_event(
            conn, db_path, item_id, project=project
        )
        envelope = build_envelope(
            event_name,
            event_kind=event_kind,
            event_type=event_type,
            source_type=source_type,
            session_id=session_id,
            severity=severity,
            outcome=outcome,
            user_id=user_id,
            org_id=org_id,
            environment=environment,
            request_id=request_id,
            project=project,
            item_id=resolved_item_id,
            task_num=task_num,
            agent=agent,
            tool_name=tool_name,
            duration_ms=duration_ms,
            exit_code=exit_code,
            trace_id=trace_id,
            parent_id=parent_id,
            anomaly_flags=anomaly_flags,
            tool_use_id=tool_use_id,
            turn_id=turn_id,
            hook_event_name=hook_event_name,
            auth_context=auth_context,
            context=context,
            created_at=created_at,
        )

        capture_file = os.environ.get("YOKE_EVENTS_FILE")
        if os.environ.get("YOKE_EVENTS_CAPTURE") == "1" and capture_file:
            with open(capture_file, "a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(envelope, separators=(",", ":"), ensure_ascii=False)
                    + "\n"
                )
            return EmitResult(False, envelope["event_id"], "capture_only", envelope)

        # Isolation gate: refuse live-ledger writes when the
        # process declares test isolation and the caller has not opted in.
        resolved_target = db_path if db_path is not None else None if conn is not None else _resolve_db_path()
        if isolation_gate_blocks(
            db_path=resolved_target,
            anomaly_flags=anomaly_flags,
            has_explicit_conn=conn is not None,
        ):
            logger.debug(
                "Isolation gate refused live-ledger write for %s "
                "(capture/isolation mode active, no escape hatch configured)",
                event_name,
            )
            return EmitResult(
                False, envelope["event_id"], "isolation_gate_refused", envelope,
            )

        assert_event_name_not_retired(conn or resolved_target, event_name)
        passes_severity = (
            check_severity_conn(conn, event_name, source_type, envelope["severity"])
            if conn is not None
            else check_severity(
                resolved_target, event_name, source_type, envelope["severity"]
            )
        )
        if not passes_severity:
            return EmitResult(False, envelope["event_id"], "severity_filtered", envelope)
        wrote = _write_event(envelope, db_path=db_path, conn=conn)
        return EmitResult(wrote, envelope["event_id"], "" if wrote else "exception", envelope)

    except RetiredEventNameError: raise
    except Exception as exc:
        logger.debug("Native event emission failed for %s: %s", event_name, exc)
        exc_text = str(exc)
        missing = "no such table: events" in exc_text or 'relation "events" does not exist' in exc_text
        reason = "events_table_missing" if missing else "exception"
        return EmitResult(False, None, reason, None)


def _write_event(
    envelope: Dict[str, Any],
    *,
    db_path: Optional[str] = None,
    conn: Optional[Any] = None,
) -> bool:
    """Insert an event row into the events table.

    If ``conn`` is provided, uses it directly (caller manages lifecycle).
    Otherwise opens a short-lived connection to the resolved DB path.
    """
    if conn is not None:
        apply_session_actor_id(envelope, conn=conn)
        project_id = resolve_envelope_project_id_for_event(conn, db_path, envelope)
        return write_event_row_on_conn(
            conn, _INSERT_SQL, event_insert_params(envelope, project_id)
        )

    own_conn = db_backend.connect(db_path)
    try:
        apply_session_actor_id(envelope, conn=own_conn)
        project_id = resolve_envelope_project_id_for_event(
            own_conn, db_path, envelope
        )
        return write_event_row_on_conn(
            own_conn, _INSERT_SQL, event_insert_params(envelope, project_id)
        )
    finally:
        own_conn.close()


# Re-export the legacy argv-compat helper at the original import path.
from .events_argv_compat import emit_event_argv  # noqa: E402,F401
