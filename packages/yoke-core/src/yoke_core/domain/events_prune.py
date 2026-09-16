"""Per-severity retention pruning for the Yoke event platform.

Owns ``cmd_prune`` plus the ``record_audit_fingerprint`` integration that
records each non-dry-run prune as a documented retention-only exception
to the governed-migration contract. Event deletes are LIMIT-batched and
time-bounded; preview counts use the same probe. Operational-table TTLs
stay in their existing helpers and are not expanded here.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from yoke_core.domain.db_helpers import connect, query_scalar
from yoke_core.domain import (
    db_backend,
    function_call_ledger,
    github_workflow_dispatch_intents,
)
from yoke_core.domain.events_prune_batches import (
    EVENT_PRUNE_BATCH_SIZE,
    EVENT_PRUNE_MAX_SECONDS,
    EVENT_RETENTION_DAYS,
    SESSION_TOOL_CALLS_RETENTION_DAYS,
    coerce_batch_size,
    prune_matching_events,
    reference_exclusion_sql,
)
from yoke_core.domain.events_prune_report import (
    dry_run_report,
    emit_audit,
    intent_count,
    ledger_count,
)
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.time_sql import now_sql
from yoke_core.domain.populate_registry_data_authoritative import (
    PURGED_EVENT_NAMES,
)


def prune_cli_kwargs(argv: Optional[list[str]] = None) -> dict[str, Any]:
    """Parse ``events prune`` flags into ``cmd_prune`` kwargs."""
    args = list(argv or [])
    kwargs: dict[str, Any] = {
        "dry_run": "--dry-run" in args,
        "purge_obsolete": "--purge-obsolete" in args,
    }

    def _value(flag: str) -> Optional[str]:
        if flag not in args:
            return None
        index = args.index(flag)
        if index + 1 >= len(args):
            raise ValueError(f"{flag} requires a value")
        return args[index + 1]

    raw_batch = _value("--batch-size")
    if raw_batch is not None:
        kwargs["batch_size"] = int(raw_batch)
    raw_seconds = _value("--max-seconds")
    if raw_seconds is not None:
        kwargs["max_seconds"] = float(raw_seconds)
    raw_batches = _value("--max-batches")
    if raw_batches is not None:
        kwargs["max_batches"] = int(raw_batches)
    return kwargs


def _purged_event_where(conn: Any) -> tuple[str, tuple[str, ...]]:
    """Predicate for opt-in obsolete-name cleanup, with reference guards."""
    placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"
    names = tuple(PURGED_EVENT_NAMES)
    where = (
        "event_name IN ("
        + ", ".join(placeholder for _ in names)
        + ")"
        + reference_exclusion_sql(conn)
    )
    return where, names


def _severity_where(conn: Any, severity: str, days: int) -> str:
    if severity not in EVENT_RETENTION_DAYS:
        raise ValueError(f"unknown event severity {severity!r}")
    quoted = severity.replace("'", "''")
    return (
        f"severity='{quoted}' AND created_at < {now_sql(offset_days=-days)}"
        + reference_exclusion_sql(conn)
    )


def cmd_prune(
    db_path: Optional[str] = None,
    dry_run: bool = False,
    *,
    batch_size: int = EVENT_PRUNE_BATCH_SIZE,
    max_seconds: float = EVENT_PRUNE_MAX_SECONDS,
    max_batches: int | None = None,
    purge_obsolete: bool = False,
) -> str:
    """Per-severity event retention (+ existing rolling-state TTLs).

    Event preview and deletion are LIMIT-batched and time-bounded.
    STATUS/ERROR/FATAL are never age-pruned. Referenced event_id rows
    are kept on every event delete path. Obsolete-name purge is opt-in.
    """
    batch = coerce_batch_size(batch_size)
    if max_seconds <= 0:
        raise ValueError("max_seconds must be positive")
    if max_batches is not None and max_batches < 1:
        raise ValueError("max_batches must be a positive integer")
    conn = connect(db_path)
    try:
        has_tool_calls = _table_exists(conn, "session_tool_calls")
        if dry_run:
            return dry_run_report(
                conn,
                batch,
                has_tool_calls,
                purge_obsolete,
                severity_where=_severity_where,
                purged_event_where=_purged_event_where,
            )
        return _run_prune(
            conn,
            batch=batch,
            max_seconds=max_seconds,
            max_batches=max_batches,
            has_tool_calls=has_tool_calls,
            purge_obsolete=purge_obsolete,
        )
    finally:
        conn.close()


def _run_prune(
    conn: Any,
    *,
    batch: int,
    max_seconds: float,
    max_batches: int | None,
    has_tool_calls: bool,
    purge_obsolete: bool,
) -> str:
    deadline = time.monotonic() + max_seconds
    batches_left: list[int | None] = [max_batches]
    pre_ledger = ledger_count(conn)
    pre_intents = intent_count(conn)
    pre_tool_calls = 0
    if has_tool_calls:
        pre_tool_calls = int(
            query_scalar(conn, "SELECT COUNT(*) FROM session_tool_calls") or 0
        )
    pruned = {
        name: 0 for name, days in EVENT_RETENTION_DAYS.items() if days is not None
    }
    more_remaining = False
    for severity, days in EVENT_RETENTION_DAYS.items():
        if days is None:
            continue
        deleted, remaining = prune_matching_events(
            conn,
            _severity_where(conn, severity, days),
            batch_size=batch,
            deadline=deadline,
            batches_left=batches_left,
        )
        pruned[severity] = deleted
        more_remaining = more_remaining or remaining
    purged_events = 0
    if purge_obsolete:
        where, params = _purged_event_where(conn)
        deleted, remaining = prune_matching_events(
            conn,
            where,
            params,
            batch_size=batch,
            deadline=deadline,
            batches_left=batches_left,
        )
        purged_events = deleted
        more_remaining = more_remaining or remaining
    ledger_pruned = function_call_ledger.prune_expired(conn)
    intents_pruned = github_workflow_dispatch_intents.prune_expired(conn)
    tool_calls_pruned = 0
    if has_tool_calls:
        tool_calls_pruned = conn.execute(
            "DELETE FROM session_tool_calls "
            f"WHERE started_at < {now_sql(offset_days=-SESSION_TOOL_CALLS_RETENTION_DAYS)}"
        ).rowcount
    conn.commit()
    event_deleted = sum(pruned.values()) + purged_events
    lines = [
        "Pruned: "
        + ", ".join(f"{name}={pruned[name]}" for name in pruned)
        + f", function_call_ledger={ledger_pruned}, "
        f"github_workflow_dispatch_intents={intents_pruned}, "
        f"session_tool_calls={tool_calls_pruned}, obsolete={purged_events}"
    ]
    if more_remaining:
        lines.append(
            "stopped: batch/time budget; rerun the same command to continue "
            "(idempotent leftover eligible rows)"
        )
    emit_audit(
        pruned=pruned,
        purged_events=purged_events,
        event_deleted=event_deleted,
        ledger_pruned=ledger_pruned,
        intents_pruned=intents_pruned,
        tool_calls_pruned=tool_calls_pruned,
        pre_ledger=pre_ledger,
        pre_intents=pre_intents,
        pre_tool_calls=pre_tool_calls,
        more_remaining=more_remaining,
    )
    return "\n".join(lines)
