"""Dry-run text and migration_audit fingerprint for event retention."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import (
    db_backend,
    function_call_ledger,
    github_workflow_dispatch_intents,
)
from yoke_core.domain.db_helpers import query_scalar
from yoke_core.domain.events_prune_batches import (
    EVENT_RETENTION_DAYS,
    SESSION_TOOL_CALLS_RETENTION_DAYS,
    StatementBudgetExceeded,
    bounded_event_count,
    current_statement_timeout,
    format_bounded_count,
    restore_event_prune_statement_timeout,
)
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.time_sql import now_sql


def ledger_count(conn: Any) -> int:
    if not _table_exists(conn, function_call_ledger.LEDGER_TABLE):
        return 0
    return int(
        query_scalar(
            conn,
            f"SELECT COUNT(*) FROM {function_call_ledger.LEDGER_TABLE}",
        )
        or 0
    )


def intent_count(conn: Any) -> int:
    table = github_workflow_dispatch_intents.INTENT_TABLE
    if not _table_exists(conn, table):
        return 0
    return int(query_scalar(conn, f"SELECT COUNT(*) FROM {table}") or 0)


def dry_run_report(
    conn: Any,
    batch: int,
    has_tool_calls: bool,
    purge_obsolete: bool,
    *,
    deadline: float,
    severity_where,
    purged_event_where,
) -> str:
    parts: list[str] = []
    obsolete_note = "obsolete=skipped"
    stopped = False
    prior_timeout = current_statement_timeout(conn)
    try:
        for severity, days in EVENT_RETENTION_DAYS.items():
            if days is None:
                continue
            count, partial = bounded_event_count(
                conn,
                severity_where(conn, severity, days),
                limit=batch,
                deadline=deadline,
                restore_timeout=prior_timeout,
            )
            parts.append(f"{severity}={format_bounded_count(count, partial)}")
        if purge_obsolete:
            where, params = purged_event_where(conn)
            count, partial = bounded_event_count(
                conn,
                where,
                params,
                limit=batch,
                deadline=deadline,
                restore_timeout=prior_timeout,
            )
            obsolete_note = f"obsolete={format_bounded_count(count, partial)}"
    except StatementBudgetExceeded:
        stopped = True
    finally:
        restore_event_prune_statement_timeout(conn, prior_timeout)
    tool_call_count = 0
    if has_tool_calls:
        tool_call_count = query_scalar(
            conn,
            "SELECT COUNT(*) FROM session_tool_calls "
            f"WHERE started_at < {now_sql(offset_days=-SESSION_TOOL_CALLS_RETENTION_DAYS)}",
        )
    counted = ", ".join(parts) if parts else "(timeout before first count)"
    lines = [
        f"Would prune: {counted}, {obsolete_note}",
        "(STATUS/ERROR/FATAL retained indefinitely; STATUS not counted)",
        f"function_call_ledger: {function_call_ledger.count_expired(conn)} "
        f"rows past {function_call_ledger.LEDGER_TTL_DAYS}d replay TTL",
        "github_workflow_dispatch_intents: "
        f"{github_workflow_dispatch_intents.count_expired(conn)} terminal "
        "row(s) past "
        f"{github_workflow_dispatch_intents.INTENT_TTL_DAYS}d TTL "
        "(pending retained indefinitely)",
        f"session_tool_calls: {tool_call_count} row(s) older than "
        f"{SESSION_TOOL_CALLS_RETENTION_DAYS}d",
        f"event batch_size={batch} (counts are exact or labeled partial)",
    ]
    if stopped:
        lines.append(
            "stopped: batch/time budget; rerun the same command to continue "
            "(idempotent leftover eligible rows)"
        )
    return "\n".join(lines)


def emit_audit(
    *,
    pruned: dict[str, int],
    purged_events: int,
    event_deleted: int,
    ledger_pruned: int,
    intents_pruned: int,
    tool_calls_pruned: int,
    pre_ledger: int,
    pre_intents: int,
    pre_tool_calls: int,
    more_remaining: bool,
) -> None:
    """Fingerprint this pass's exact deletes; skip table-wide event COUNT."""
    from yoke_core.domain.migration_harness import record_audit_fingerprint

    stop_note = " more remaining (rerun)." if more_remaining else "."
    record_audit_fingerprint(
        db_path=db_backend.resolve_pg_dsn(),
        name="events-prune",
        description=(
            "Retention-only prune this pass (exact batch totals, no "
            "table-wide events COUNT): "
            + ", ".join(f"{name}={pruned[name]}" for name in pruned)
            + f" (STATUS never pruned); function_call_ledger="
            f"{ledger_pruned} past the "
            f"{function_call_ledger.LEDGER_TTL_DAYS}d replay TTL; "
            "github_workflow_dispatch_intents="
            f"{intents_pruned} terminal rows past the "
            f"{github_workflow_dispatch_intents.INTENT_TTL_DAYS}d TTL "
            "(pending never age-pruned); "
            f"session_tool_calls rows older than "
            f"{SESSION_TOOL_CALLS_RETENTION_DAYS}d="
            f"{tool_calls_pruned}; obsolete event rows="
            f"{purged_events}{stop_note}"
        ),
        tables=[
            "events",
            function_call_ledger.LEDGER_TABLE,
            github_workflow_dispatch_intents.INTENT_TABLE,
            "session_tool_calls",
        ],
        pre_counts={
            "events": event_deleted,
            function_call_ledger.LEDGER_TABLE: pre_ledger,
            github_workflow_dispatch_intents.INTENT_TABLE: pre_intents,
            "session_tool_calls": pre_tool_calls,
        },
        post_counts={
            "events": 0,
            function_call_ledger.LEDGER_TABLE: pre_ledger - ledger_pruned,
            github_workflow_dispatch_intents.INTENT_TABLE: (
                pre_intents - intents_pruned
            ),
            "session_tool_calls": pre_tool_calls - tool_calls_pruned,
        },
        exception_reason=(
            "Bounded retention exception: expected non-zero "
            "delta by severity/age (DEBUG>1d, INFO>30d, WARN>90d; "
            "idempotency-ledger rows past their replay TTL; "
            "terminal workflow-dispatch intents past their TTL, while "
            "pending ambiguous intents are preserved indefinitely; "
            "session_tool_calls rows past rolling-state retention; "
            "opt-in named obsolete events with no live producer). STATUS "
            "rows are preserved indefinitely. Event preview/delete uses "
            "indexed created_at selection with LIMIT batches; table-wide "
            "events COUNT is skipped. GovernedMigration wrap is "
            "incompatible with the delete-by-age shape; paired decision "
            "record lives at docs/archive/decisions/events-prune.md. "
            "db_error_hook row-count collapse detection is the live "
            "safety layer."
        ),
    )
