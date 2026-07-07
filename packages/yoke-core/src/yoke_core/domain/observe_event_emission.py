"""Envelope construction and event insertion for observe telemetry."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from yoke_core.domain import db_backend
from yoke_core.domain.events_tool_call_outcome import (
    OUTCOME_COMPLETED,
    OUTCOME_DENIED,
    OUTCOME_FAILED,
    OUTCOME_STRUCTURED_EXIT,
    classify_tool_call_outcome,
)
from yoke_core.domain.observe_parsing import EventRecord
from yoke_core.domain.events_project_identity import (
    resolve_envelope_project_id_for_event,
)

# event_outcome -> event_name mapping. Lifecycle_mutation and structured_exit
# reshapes layer on top of this baseline below.
_OUTCOME_TO_EVENT_NAME: Dict[str, str] = {
    OUTCOME_COMPLETED: "HarnessToolCallCompleted",
    OUTCOME_FAILED: "HarnessToolCallFailed",
    OUTCOME_DENIED: "HarnessToolCallFailed",
    OUTCOME_STRUCTURED_EXIT: "HarnessToolCallStructuredExit",
}


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def build_envelope(rec: EventRecord) -> Dict[str, Any]:
    """Build the full event envelope dict for DB insertion."""
    anomalies = rec.anomalies
    anomaly_flags = ",".join(anomalies) if anomalies else None
    benign_failure = "benign_failure" in anomalies
    structured_exit = "structured_exit" in anomalies

    # event_outcome + exit_code come from the central classifier so
    # observe / dispatcher / sweep emitters all share one vocabulary.
    event_outcome, classified_exit_code = classify_tool_call_outcome(rec)
    event_name = _OUTCOME_TO_EVENT_NAME[event_outcome]
    severity = "INFO" if event_outcome == OUTCOME_COMPLETED else "WARN"

    # lifecycle_mutation
    if "lifecycle_mutation" in anomalies:
        severity = "WARN"
        event_name = "HarnessLifecycleMutationDetected"

    # structured exit (already named via classifier — keep severity sane)
    if structured_exit:
        severity = "INFO"
    elif benign_failure:
        severity = "INFO"

    # Elevate severity for anomalies (not benign/structured/unattributed-only)
    if anomaly_flags and not rec.is_failure and not benign_failure and not structured_exit:
        if anomalies == ["unattributed"]:
            pass  # main-session unattributed is expected
        else:
            severity = "WARN"

    event_id = str(uuid.uuid4())
    event_time = (
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.")
        + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"
    )

    # Context JSON — enriched during task 005
    context: Dict[str, Any] = {"tool_name": rec.tool_name}

    # tool_input: truncated command for Bash, file_path for file ops
    if rec.command:
        context["tool_input"] = rec.command[:2048]
    elif rec.file_path:
        context["tool_input"] = rec.file_path

    # tool_response_preview (was response_preview)
    if rec.response_text:
        context["tool_response_preview"] = rec.response_text[:512]
    if rec.hook_error:
        context["error"] = rec.hook_error[:2048]
    if rec.attribution_source:
        context["attribution_source"] = rec.attribution_source
    if rec.hook_event:
        context["hook_event"] = rec.hook_event
    if rec.agent_type:
        # actor_role disambiguates which dispatched subagent role authored the
        # tool call within the parent harness session (Codex `agent:` dispatch
        # and Claude `Agent`-tool subagent both share session_id with the
        # parent). Parent-turn calls omit the field. Sources: hook payload
        # ``agent_type``, rendered ``--agent-type``, or the
        # YOKE_HOOK_AGENT_TYPE signal from ``agents_render_subagent_hooks``.
        context["actor_role"] = rec.agent_type
    if rec.has_permission_decision:
        context["decision_metadata"] = {}  # placeholder for future enrichment

    # Cap context.detail at 4KB
    _ctx_json = json.dumps(context, separators=(",", ":"))
    if len(_ctx_json.encode("utf-8")) > 4096:
        # Truncate tool_input and tool_response_preview to fit
        if "tool_input" in context:
            context["tool_input"] = context["tool_input"][:1024]
        if "tool_response_preview" in context:
            context["tool_response_preview"] = context["tool_response_preview"][:256]
        if "error" in context:
            context["error"] = context["error"][:1024]

    envelope: Dict[str, Any] = {
        "event_id": event_id,
        "event_name": event_name,
        "event_kind": "system",
        "event_type": "tool_call",
        "event_time": event_time,
        "event_outcome": event_outcome,
        "source_type": "agent",
        "severity": severity,
        "session_id": rec.session_id,
        "service": "cli",
        "project": "yoke",
        "environment": None,
        "user_id": None,
        "org_id": None,
        "actor": None,
        "agent": rec.agent_type,
        "item_id": rec.item_id,
        "task_num": rec.task_num,
        "tool_name": rec.tool_name or None,
        "duration_ms": rec.duration_ms,
        "exit_code": classified_exit_code,
        "trace_id": None,
        "parent_id": None,
        "anomaly_flags": anomaly_flags,
        "attribution_source": rec.attribution_source or None,
        "tool_use_id": rec.tool_use_id,
        "turn_id": rec.turn_id,
        "hook_event_name": rec.hook_event,
        "context": {"detail": context},
    }

    envelope_json = json.dumps(envelope, separators=(",", ":"))
    if len(envelope_json.encode("utf-8")) > 65536:
        envelope["context"] = {
            "detail": {"tool_name": rec.tool_name, "truncated": True}
        }
        envelope["_truncated"] = True

    return envelope


def insert_event(conn: Any, envelope: Dict[str, Any]) -> None:
    """Insert an event envelope into the events table.

    Silently no-ops if the events table does not exist. Tool-call-shaped
    envelopes additionally project onto the session activity state
    (``harness_sessions.last_tool_call_at`` / ``tool_call_count`` and the
    ``session_tool_calls`` rolling table) in the same transaction — the
    events ledger is telemetry-only; the state columns are what runtime
    behaviors read.
    """
    try:
        conn.execute("SELECT 1 FROM events LIMIT 1")
    except db_backend.operational_error_types(conn):
        return

    envelope_json = json.dumps(envelope, separators=(",", ":"))
    # Re-validate JSON
    json.loads(envelope_json)

    task_num = envelope.get("task_num")
    if task_num is not None:
        task_num = int(task_num)

    project_id = resolve_envelope_project_id_for_event(conn, None, envelope)

    values = (
        envelope["event_id"],
        "agent",
        envelope["session_id"],
        envelope["severity"],
        "system",
        "tool_call",
        envelope["event_name"],
        envelope["event_outcome"],
        "cli",
        project_id,
        envelope.get("item_id"),
        task_num,
        envelope.get("agent"),
        envelope.get("tool_name"),
        envelope.get("duration_ms"),
        envelope.get("exit_code"),
        envelope.get("anomaly_flags"),
        envelope.get("tool_use_id"),
        envelope.get("turn_id"),
        envelope.get("hook_event_name"),
        envelope_json,
        envelope["event_time"],
    )

    placeholders = ", ".join([_p(conn)] * len(values))
    conn.execute(
        """INSERT INTO events (
            event_id, source_type, session_id, severity,
            event_kind, event_type, event_name, event_outcome,
            service, project_id, item_id, task_num,
            agent, tool_name, duration_ms, exit_code,
            anomaly_flags, tool_use_id, turn_id,
            hook_event_name, envelope, created_at
        ) VALUES ("""
        + placeholders
        + """)
        ON CONFLICT(event_id) DO NOTHING""",
        values,
    )
    # Same-transaction state write: Started opens a session_tool_calls
    # row; Completed/Failed (and siblings) close it and bump
    # last_tool_call_at / tool_call_count. Schema-tolerant — skips
    # cleanly on fixtures lacking the table/columns.
    from yoke_core.domain.session_activity_state import apply_envelope_state

    apply_envelope_state(conn, envelope)
    conn.commit()
