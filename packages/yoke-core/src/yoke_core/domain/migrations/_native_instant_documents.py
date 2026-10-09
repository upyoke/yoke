"""One-time repairs of mutable owned clocks, preserving unrelated document facts.

The finite field policies here are permanent history, not runtime codecs.
Calendar/offset-free historical strings assume UTC. Missing required clocks use
existing owner facts; optional unknown usage observations become JSON null.
No immutable artifact, signed document, token counter or identity is rewritten.
"""

from dataclasses import dataclass
from datetime import datetime
import json
import re
from typing import Any

from psycopg import sql

from yoke_contracts.timestamps import InvalidInstant, format_instant
from yoke_core.domain.json_helper import dumps_compact
from yoke_core.domain.qa_plan_execution_store import canonical


@dataclass(frozen=True)
class DocumentUpdate:
    table: str
    key_column: str
    key: Any
    column: str
    before: str
    after: str


def _historical_clock(conn: Any, value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return format_instant(value)
    if not isinstance(value, str):
        return None
    try:
        return format_instant(value)
    except InvalidInstant:
        # This is a one-time UTC assumption, never an accepted future encoding.
        value = re.sub(r"([.][0-9]{6})[0-9]+", r"\1", value)
        valid = conn.execute(
            "SELECT pg_input_is_valid(%s,'timestamp with time zone')", (value,)
        ).fetchone()[0]
        if not valid:
            return None
        return format_instant(
            conn.execute("SELECT %s::timestamptz", (value,)).fetchone()[0]
        )


def _clock(
    conn: Any, value: Any, facts: tuple[Any, ...], *, optional=False
) -> str | None:
    if optional and (value is None or value == ""):
        return None
    for candidate in (value, *facts):
        repaired = _historical_clock(conn, candidate)
        if repaired is not None:
            return repaired
    raise RuntimeError(
        "instant_document_owner_fact_unavailable: a required owned clock has "
        "no usable historical value or owner fact. Recovery: inspect the restored "
        "owner record and declare its deterministic repair before rehearsal."
    )


def _rows(
    conn: Any,
    table: str,
    key: str,
    column: str,
    facts: tuple[str, ...],
    *,
    kind: str | None = None,
) -> list[Any]:
    names = {
        r[0]
        for r in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=%s",
            (table,),
        ).fetchall()
    }
    if not {key, column}.issubset(names) or (kind is not None and "kind" not in names):
        return []
    fields = [sql.Identifier(key), sql.Identifier(column)]
    fields += [
        sql.Identifier(name) if name in names else sql.SQL("NULL") for name in facts
    ]
    statement = sql.SQL("SELECT {} FROM {} WHERE {} IS NOT NULL AND {} <> ''").format(
        sql.SQL(",").join(fields),
        sql.Identifier(table),
        sql.Identifier(column),
        sql.Identifier(column),
    )
    if kind is not None:
        statement += sql.SQL(" AND kind=%s")
        return conn.execute(statement, (kind,)).fetchall()
    return conn.execute(statement).fetchall()


def _document(raw: str, table: str, key: Any) -> dict[str, Any]:
    try:
        value = json.loads(raw)
        if isinstance(value, dict):
            return value
    except (ValueError, TypeError):
        pass
    raise RuntimeError(
        f"instant_document_unreadable: {table} owner {key}. Recovery: inspect "
        "this restored mutable document before defining its repair; no data changed."
    )


def _add(
    updates: list[DocumentUpdate],
    table: str,
    key: str,
    row: Any,
    column: str,
    after: str,
) -> None:
    if row[1] != after:
        updates.append(DocumentUpdate(table, key, row[0], column, row[1], after))


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
    from yoke_core.domain.migrations._native_relay_instant_documents import (
        prepare_relay_document_updates,
    )

    updates.extend(prepare_relay_document_updates(conn))
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
