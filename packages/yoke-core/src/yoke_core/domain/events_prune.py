"""Per-severity retention pruning for the Yoke event platform.

Owns ``cmd_prune`` plus the ``record_audit_fingerprint`` integration that
records each non-dry-run prune as a documented retention-only exception
to the governed-migration contract. The audit-helper import stays lazy
inside the function body to avoid a circular import with
``yoke_core.domain.migration_harness``.
"""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.db_helpers import connect, query_scalar
from yoke_core.domain import db_backend, function_call_ledger
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.time_sql import now_sql

# Rolling-state retention for session_tool_calls (Session-tool-call). 7 days
# comfortably covers every reader: the lints look back <=30 minutes and
# the orphan sweep runs at session end.
SESSION_TOOL_CALLS_RETENTION_DAYS = 7


def _ledger_count(conn) -> int:
    """Total ledger rows for the audit fingerprint (0 when absent)."""
    if not _table_exists(conn, function_call_ledger.LEDGER_TABLE):
        return 0
    return int(
        query_scalar(
            conn,
            f"SELECT COUNT(*) FROM {function_call_ledger.LEDGER_TABLE}",
        )
        or 0
    )


def cmd_prune(db_path: Optional[str] = None, dry_run: bool = False) -> str:
    """Per-severity retention pruning (+ rolling-state TTLs).

    bounded retention-only destructive maintenance. Not wrapped
    in ``GovernedMigration`` because the operation has non-zero expected
    delta by design (DEBUG > 1d, INFO > 30d, WARN > 90d; STATUS never
    pruned; ``function_call_ledger`` rows past their replay TTL;
    ``session_tool_calls`` rows past their rolling-state retention).
    Instead, a ``migration_audit`` fingerprint is emitted after
    a real (non-dry-run) prune so the destructive-maintenance doctor HC
    can surface the operation.  The fingerprint carries:

    - pre/post row counts for ``events``, ``function_call_ledger``, and
      ``session_tool_calls``
    - pruned counts by severity, recorded in ``description``
    - an ``exception_note`` explaining why this path is a documented
      retention-only exception
    """
    conn = connect(db_path)
    try:
        has_tool_calls = _table_exists(conn, "session_tool_calls")
        if dry_run:
            debug_count = query_scalar(
                conn,
                "SELECT COUNT(*) FROM events "
                f"WHERE severity='DEBUG' AND created_at < {now_sql(offset_days=-1)}",
            )
            info_count = query_scalar(
                conn,
                "SELECT COUNT(*) FROM events "
                f"WHERE severity='INFO' AND created_at < {now_sql(offset_days=-30)}",
            )
            warn_count = query_scalar(
                conn,
                "SELECT COUNT(*) FROM events "
                f"WHERE severity='WARN' AND created_at < {now_sql(offset_days=-90)}",
            )
            status_count = query_scalar(
                conn, "SELECT COUNT(*) FROM events WHERE severity='STATUS'"
            )
            ledger_count = function_call_ledger.count_expired(conn)
            tool_call_count = query_scalar(
                conn,
                "SELECT COUNT(*) FROM session_tool_calls "
                f"WHERE started_at < {now_sql(offset_days=-SESSION_TOOL_CALLS_RETENTION_DAYS)}",
            ) if has_tool_calls else 0
            lines = [
                f"Would prune: DEBUG={debug_count}, INFO={info_count}, WARN={warn_count}",
                f"(STATUS={status_count} events retained indefinitely)",
                f"function_call_ledger: {ledger_count} rows past "
                f"{function_call_ledger.LEDGER_TTL_DAYS}d replay TTL",
                f"session_tool_calls: {tool_call_count} row(s) older than "
                f"{SESSION_TOOL_CALLS_RETENTION_DAYS}d",
            ]
            return "\n".join(lines)
        else:
            # capture pre-prune row counts for the audit fingerprint.
            pre_count = int(
                query_scalar(conn, "SELECT COUNT(*) FROM events") or 0
            )
            pre_ledger = _ledger_count(conn)
            pre_tool_calls = int(
                query_scalar(
                    conn, "SELECT COUNT(*) FROM session_tool_calls"
                ) or 0
            ) if has_tool_calls else 0
            # cursor.rowcount gives rows-affected on Postgres.
            debug_pruned = conn.execute(
                "DELETE FROM events WHERE severity='DEBUG' "
                f"AND created_at < {now_sql(offset_days=-1)}"
            ).rowcount
            info_pruned = conn.execute(
                "DELETE FROM events WHERE severity='INFO' "
                f"AND created_at < {now_sql(offset_days=-30)}"
            ).rowcount
            warn_pruned = conn.execute(
                "DELETE FROM events WHERE severity='WARN' "
                f"AND created_at < {now_sql(offset_days=-90)}"
            ).rowcount
            ledger_pruned = function_call_ledger.prune_expired(conn)
            # session_tool_calls is a short-retention rolling state table:
            # the orphan sweep closes rows at session end and the lint
            # guardrails look back minutes, so anything older than the
            # window is inert. Open rows that old are themselves garbage
            # (their session ended without a sweep) and prune with it.
            tool_calls_pruned = conn.execute(
                "DELETE FROM session_tool_calls "
                f"WHERE started_at < {now_sql(offset_days=-SESSION_TOOL_CALLS_RETENTION_DAYS)}"
            ).rowcount if has_tool_calls else 0
            conn.commit()

            lines = [
                f"Pruned: DEBUG={debug_pruned}, INFO={info_pruned}, "
                f"WARN={warn_pruned}, function_call_ledger={ledger_pruned}, "
                f"session_tool_calls={tool_calls_pruned}"
            ]

            # Emit an audit fingerprint so the prune is discoverable
            # alongside governed migrations. The helper is fail-closed:
            # an ``AuditEmissionError`` propagates out of ``cmd_prune``
            # so the operator sees a loud failure if the durable evidence
            # cannot be written. Recovery contract: retention deletes
            # have already committed, so the operator repairs the audit
            # emission path (DB connectivity, schema constraints, etc.)
            # and reruns the idempotent prune — they do NOT try to
            # restore the pruned rows.
            post_count = int(
                query_scalar(conn, "SELECT COUNT(*) FROM events") or 0
            )
            post_ledger = _ledger_count(conn)
            post_tool_calls = int(
                query_scalar(
                    conn, "SELECT COUNT(*) FROM session_tool_calls"
                ) or 0
            ) if has_tool_calls else 0
            resolved_db = db_backend.resolve_pg_dsn()
            from yoke_core.domain.migration_harness import (
                record_audit_fingerprint,
            )
            record_audit_fingerprint(
                db_path=resolved_db,
                name="events-prune",
                description=(
                    f"Retention-only prune: DEBUG={debug_pruned}, "
                    f"INFO={info_pruned}, WARN={warn_pruned} "
                    f"(STATUS never pruned); function_call_ledger="
                    f"{ledger_pruned} past the "
                    f"{function_call_ledger.LEDGER_TTL_DAYS}d replay TTL; "
                    f"session_tool_calls rows older than "
                    f"{SESSION_TOOL_CALLS_RETENTION_DAYS}d="
                    f"{tool_calls_pruned}."
                ),
                tables=[
                    "events",
                    function_call_ledger.LEDGER_TABLE,
                    "session_tool_calls",
                ],
                pre_counts={
                    "events": pre_count,
                    function_call_ledger.LEDGER_TABLE: pre_ledger,
                    "session_tool_calls": pre_tool_calls,
                },
                post_counts={
                    "events": post_count,
                    function_call_ledger.LEDGER_TABLE: post_ledger,
                    "session_tool_calls": post_tool_calls,
                },
                exception_reason=(
                    "Bounded retention exception: expected non-zero "
                    "delta by severity/age (DEBUG>1d, INFO>30d, WARN>90d; "
                    "idempotency-ledger rows past their replay TTL; "
                    "session_tool_calls rows past rolling-state retention). "
                    "STATUS rows are preserved indefinitely. "
                    "GovernedMigration wrap is incompatible with the "
                    "delete-by-age shape; paired decision record lives at "
                    "docs/archive/decisions/events-prune.md. "
                    "db_error_hook row-count collapse detection is the "
                    "live safety layer."
                ),
            )

            return "\n".join(lines)
    finally:
        conn.close()
