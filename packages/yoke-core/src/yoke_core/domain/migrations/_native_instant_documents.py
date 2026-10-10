"""One-time repairs of mutable owned clocks, preserving unrelated document facts.

The finite field policies here are permanent history, not runtime codecs.
Calendar/offset-free historical strings assume UTC. Missing required clocks use
existing owner facts; optional unknown usage observations become JSON null.
No immutable artifact, signed document, token counter or identity is rewritten.
"""

import json
from typing import Any

from psycopg import sql

from yoke_core.domain.json_helper import dumps_compact
from yoke_core.domain.qa_plan_execution_store import canonical

from pathlib import Path
import runpy

_FIELDS = runpy.run_path(
    str(Path(__file__).with_name("_native_instant_document_fields.py"))
)
DocumentUpdate = _FIELDS["DocumentUpdate"]
_add = _FIELDS["_add"]
_clock = _FIELDS["_clock"]
_document = _FIELDS["_document"]
_rows = _FIELDS["_rows"]


def prepare_document_updates(conn: Any) -> list[DocumentUpdate]:
    """Validate every mutable clock and prepare updates without changing rows."""
    conn.execute("SET LOCAL TIME ZONE 'UTC'")
    updates: list[DocumentUpdate] = []
    facts = (
        "native_turn_end_recorded_at",
        "last_tool_call_at",
        "episode_started_at",
        "last_heartbeat",
    )
    for row in _rows(
        conn, "harness_sessions", "session_id", "vendor_resume_episode_key", facts
    ):
        after = _clock(conn, row[1], tuple(row[2:]))
        _add(
            updates,
            "harness_sessions",
            "session_id",
            row,
            "vendor_resume_episode_key",
            after,
        )
    facts = ("last_tool_call_at", "last_heartbeat", "episode_started_at")
    for row in _rows(conn, "harness_sessions", "session_id", "usage_totals", facts):
        doc = _document(row[1], "harness_sessions", row[0])
        after = _clock(conn, doc.get("observed_at"), tuple(row[2:]), optional=True)
        if "observed_at" not in doc or doc["observed_at"] != after:
            doc["observed_at"] = after
            _add(
                updates,
                "harness_sessions",
                "session_id",
                row,
                "usage_totals",
                json.dumps(doc),
            )
    facts = ("episode_started_at", "last_heartbeat", "offered_at")
    for row in _rows(
        conn, "harness_sessions", "session_id", "pending_resume_notice", facts
    ):
        doc = _document(row[1], "harness_sessions", row[0])
        after = _clock(conn, doc.get("reactivated_at"), tuple(row[2:]))
        if doc.get("reactivated_at") != after:
            doc["reactivated_at"] = after
            _add(
                updates,
                "harness_sessions",
                "session_id",
                row,
                "pending_resume_notice",
                dumps_compact(doc),
            )
    facts = ("started_at", "created_at", "current_stage_entered_at")
    for row in _rows(conn, "deployment_runs", "id", "driver_attachment", facts):
        doc = _document(row[1], "deployment_runs", row[0])
        attached = _clock(conn, doc.get("attached_at"), tuple(row[2:4]))
        heartbeat = _clock(conn, doc.get("heartbeat_at"), (row[4], attached, *row[2:4]))
        if doc.get("attached_at") != attached or doc.get("heartbeat_at") != heartbeat:
            doc.update(attached_at=attached, heartbeat_at=heartbeat)
            _add(
                updates,
                "deployment_runs",
                "id",
                row,
                "driver_attachment",
                dumps_compact(doc),
            )
    for row in _rows(
        conn, "qa_plan_executions", "id", "release_reason", ("created_at",)
    ):
        # Other release reasons include plain prose; they are not this document owner.
        try:
            doc = json.loads(row[1])
        except (ValueError, TypeError):
            continue
        if not isinstance(doc, dict) or doc.get("kind") != "qa_host_wait":
            continue
        after = _clock(conn, doc.get("queued_at"), tuple(row[2:]))
        if doc.get("queued_at") != after:
            doc["queued_at"] = after
            _add(
                updates,
                "qa_plan_executions",
                "id",
                row,
                "release_reason",
                canonical(doc),
            )
    fields = (
        "ended_at",
        "expired_at",
        "cancelled_at",
        "canceled_at",
        "expires_at",
        "occurred_at",
        "withdrawn_at",
    )
    for row in _rows(
        conn,
        "decision_requests",
        "id",
        "subject_context",
        ("resolved_at", "withdrawn_at", "created_at"),
        kind="machine_approval",
    ):
        doc = _document(row[1], "decision_requests", row[0])
        changed = False
        for field in fields:
            if field not in doc:
                continue
            facts = (
                (row[4],) if field in {"occurred_at", "expires_at"} else tuple(row[2:])
            )
            after = _clock(conn, doc[field], facts, optional=True)
            if doc[field] != after:
                doc[field] = after
                changed = True
        if changed:
            _add(
                updates,
                "decision_requests",
                "id",
                row,
                "subject_context",
                dumps_compact(doc),
            )
    relay = runpy.run_path(
        str(Path(__file__).with_name("_native_relay_instant_documents.py"))
    )
    updates.extend(relay["prepare_relay_document_updates"](conn))
    return updates


def apply_document_updates(conn: Any, updates: list[DocumentUpdate]) -> None:
    """Publish prepared owner-field repairs, refusing concurrent mutation."""
    for update in updates:
        cursor = conn.execute(
            sql.SQL(
                "UPDATE {} SET {}=%s WHERE {}=%s AND {} IS NOT DISTINCT FROM %s"
            ).format(
                sql.Identifier(update.table),
                sql.Identifier(update.column),
                sql.Identifier(update.key_column),
                sql.Identifier(update.column),
            ),
            (update.after, update.key, update.before),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(
                f"instant_document_changed: {update.table} owner {update.key}. "
                "Recovery: stop the owning writer and restart governed rehearsal "
                "from its protected source; do not overwrite a newer document."
            )
