"""Ledger-trust health checks for the canonical events ledger.

Owns the trust-signal HCs that watch for synthetic contamination,
historical telemetry collapse, and unattested destructive maintenance:

- ``hc_events_synthetic_contamination``
- ``hc_events_historical_coverage_collapse``
- ``hc_events_destructive_maintenance_audit``
"""

from __future__ import annotations

from typing import List, Tuple

from yoke_core.domain.db_helpers import query_rows, query_scalar
from yoke_core.domain.sql_json import json_get
from yoke_core.domain.time_sql import now_sql

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def _week_bucket_sql(column: str) -> str:
    """Return a calendar-week bucket fragment for active ledger timestamps."""
    return f"to_char(({column})::timestamptz, 'IYYY-IW')"


def _day_bucket_sql(column: str) -> str:
    """Return a YYYY-MM-DD bucket fragment for operator follow-up queries."""
    return f"to_char(({column})::timestamptz, 'YYYY-MM-DD')"


def _abs_seconds_delta_sql(lhs: str, rhs: str) -> str:
    """Return absolute seconds between two timestamp columns."""
    return (
        "ABS(EXTRACT(EPOCH FROM "
        f"(({lhs})::timestamptz - ({rhs})::timestamptz)))"
    )


def hc_events_synthetic_contamination(
    conn, args: DoctorArgs, rec: RecordCollector
) -> None:
    """HC-events-synthetic-contamination: synthetic/test rows in canonical ledger.

    The canonical events ledger is supposed to hold real
    telemetry. Synthetic or test-derived rows are allowed when they are
    explicitly flagged (``anomaly_flags='historical_backfill'``), but
    unflagged synthetic rows contaminate counts and audits.

    This check surfaces:
      1. rows with a test-shaped ``session_id`` / ``service`` /
         ``event_id`` pattern that lack a canonical anomaly flag;
      2. legacy ``activity_backfill`` event_type rows still present
         (the events migration should have rewritten them to
         ``ItemStatusChanged + anomaly_flags='historical_backfill'``);
      3. rows whose ``session_id`` indicates a known test harness.

    Emits WARN with concrete counts and a follow-up command.
    """
    if not _base._table_exists(conn, "events"):
        rec.record(
            "HC-events-synthetic-contamination",
            "Synthetic or test rows in canonical events ledger",
            "PASS", "events table does not exist — skipping",
        )
        return

    issues: List[str] = []

    # 1. Legacy activity_backfill rows still present.  The rewrite tool
    # that used to rewrite these is retired — see
    # docs/archive/decisions/events-schema-rebuild-deletion.md.  Rows
    # that remain are deliberately stranded telemetry; the HC surfaces
    # their count so the operator can reconcile manually, but no live
    # remediation command is offered.
    legacy = query_scalar(
        conn,
        "SELECT COUNT(*) FROM events "
        "WHERE event_type = 'activity_backfill' OR event_name = 'ActivityBackfilled'",
    ) or 0
    if legacy:
        issues.append(
            f"- {legacy} legacy activity_backfill row(s) present — "
            "deliberately stranded telemetry; reconcile manually. See "
            "docs/archive/decisions/events-schema-rebuild-deletion.md."
        )

    # 2. Unflagged backfill-lookalike rows (session_id/service markers
    #    but no anomaly_flags='historical_backfill').
    unflagged = query_scalar(
        conn,
        # deliberate case-sensitive match against internal anomaly_flag token
        "SELECT COUNT(*) FROM events "
        "WHERE (session_id = 'lifetime-activity-backfill' "
        "       OR service = 'backfill-lifetime-activity') "
        "  AND (anomaly_flags IS NULL "
        "       OR anomaly_flags NOT LIKE '%%historical_backfill%%')",
    ) or 0
    if unflagged:
        issues.append(
            f"- {unflagged} backfill row(s) missing "
            "`anomaly_flags='historical_backfill'` — canonical audit "
            "queries will mis-count these as live telemetry."
        )

    # 3. Known test-harness session markers leaking into canonical ledger.
    test_markers = query_scalar(
        conn,
        # deliberate case-sensitive match against internal
        # session_id prefixes and service name tokens
        "SELECT COUNT(*) FROM events "
        "WHERE session_id LIKE 'test-%%' "
        "   OR session_id LIKE 'pytest-%%' "
        "   OR session_id LIKE 'fixture-%%' "
        "   OR service LIKE '%%-test' "
        "   OR service LIKE 'test-%%'",
    ) or 0
    if test_markers:
        issues.append(
            f"- {test_markers} row(s) carry a test-harness "
            "session_id/service marker. Investigate via: "
            "`python3 -m yoke_core.cli.db_router query \"SELECT "
            "source_type, session_id, service, COUNT(*) FROM events "
            "WHERE session_id LIKE 'test-%%' OR session_id LIKE "
            "'pytest-%%' OR service LIKE 'test-%%' GROUP BY 1,2,3 "
            "ORDER BY 4 DESC LIMIT 20\"`"
        )

    if issues:
        rec.record(
            "HC-events-synthetic-contamination",
            "Synthetic or test rows in canonical events ledger",
            "WARN", "\n".join(issues),
        )
    else:
        rec.record(
            "HC-events-synthetic-contamination",
            "Synthetic or test rows in canonical events ledger",
            "PASS", "",
        )


def hc_events_historical_coverage_collapse(
    conn, args: DoctorArgs, rec: RecordCollector
) -> None:
    """HC-events-historical-coverage-collapse: suspicious telemetry gap.

    A suspicious collapse in historical lifecycle telemetry coverage
    signals lost or dropped telemetry.  This check
    scans ``ItemStatusChanged`` coverage per week over the last 90 days
    and flags any week whose coverage dropped by more than 80% relative
    to the surrounding weeks' median.

    The intent is trust-signal surveillance, not alarmism: the WARN
    output includes the affected week(s) and the exact query so the
    operator can reconstruct the gap and decide whether it is explained
    by known migration or pruning events.
    """
    if not _base._table_exists(conn, "events"):
        rec.record(
            "HC-events-historical-coverage-collapse",
            "Historical delivery/status telemetry coverage",
            "PASS", "events table does not exist — skipping",
        )
        return

    # Week bucket counts for the last 90 days.
    week_bucket = _week_bucket_sql("created_at")
    rows = query_rows(
        conn,
        # deliberate case-sensitive match against internal anomaly_flag token
        f"SELECT {week_bucket} AS week, COUNT(*) AS c "
        "FROM events "
        "WHERE event_name = 'ItemStatusChanged' "
        f"  AND created_at >= {now_sql(offset_days=-90)} "
        "  AND (anomaly_flags IS NULL "
        "       OR anomaly_flags NOT LIKE '%%historical_backfill%%') "
        "GROUP BY 1 ORDER BY 1",
    )
    buckets = [(r["week"], int(r["c"])) for r in rows]

    if len(buckets) < 4:
        rec.record(
            "HC-events-historical-coverage-collapse",
            "Historical delivery/status telemetry coverage",
            "PASS",
            f"insufficient history ({len(buckets)} weeks) — need at least 4",
        )
        return

    counts = [c for _, c in buckets]
    sorted_counts = sorted(counts)
    median = sorted_counts[len(sorted_counts) // 2]
    if median <= 0:
        rec.record(
            "HC-events-historical-coverage-collapse",
            "Historical delivery/status telemetry coverage",
            "WARN",
            "median ItemStatusChanged coverage is zero over last 90 days "
            "— telemetry appears absent or lost.",
        )
        return

    collapse_threshold = max(1, median // 5)  # 80% drop trigger
    collapsed: List[Tuple[str, int]] = []
    for week, c in buckets:
        if c < collapse_threshold:
            collapsed.append((week, c))

    if collapsed:
        lines = [
            f"- Median weekly ItemStatusChanged coverage over last 90 days: "
            f"{median}. Threshold (80% drop): {collapse_threshold}."
        ]
        for week, c in collapsed:
            lines.append(f"- week {week}: only {c} row(s)")
        day_bucket = _day_bucket_sql("created_at")
        lines.append(
            "- Follow-up: `python3 -m yoke_core.cli.db_router query "
            f"\"SELECT {day_bucket}, COUNT(*) FROM events "
            "WHERE event_name='ItemStatusChanged' AND "
            "(anomaly_flags IS NULL OR anomaly_flags NOT LIKE "
            "'%%historical_backfill%%') GROUP BY 1 ORDER BY 1\"` — "
            "cross-reference against migration_audit and session backup "
            "history for the affected window."
        )
        rec.record(
            "HC-events-historical-coverage-collapse",
            "Historical delivery/status telemetry coverage",
            "WARN", "\n".join(lines),
        )
    else:
        rec.record(
            "HC-events-historical-coverage-collapse",
            "Historical delivery/status telemetry coverage",
            "PASS", "",
        )


def hc_events_destructive_maintenance_audit(
    conn, args: DoctorArgs, rec: RecordCollector
) -> None:
    """HC-events-destructive-maintenance-audit: destructive ops need evidence.

    Every destructive maintenance operation on the events
    ledger should leave behind a governed migration record OR a
    lightweight audit fingerprint. This check
    surfaces evidence-free destructive activity by comparing
    ``DataLossDetected`` alarms against the migration_audit table.

    Reports:
      1. FATAL ``DataLossDetected`` events in the last 30 days that
         have no migration_audit record (any state) within +-1 hour;
      2. migration_audit rows that completed through the exception
         pathway without a descriptive ``exception_reason`` — a sign
         that the exception-path fingerprint was not populated
         correctly.
    """
    if not _base._table_exists(conn, "events") or not _base._table_exists(
        conn, "migration_audit"
    ):
        rec.record(
            "HC-events-destructive-maintenance-audit",
            "Destructive maintenance audit evidence",
            "PASS",
            "events or migration_audit table does not exist — skipping",
        )
        return

    issues: List[str] = []

    # 1. DataLossDetected alarms without matching audit evidence
    audit_window_seconds = _abs_seconds_delta_sql("m.started_at", "e.created_at")
    unmatched = query_rows(
        conn,
        f"SELECT e.id, e.created_at, "
        f"       {json_get('e.envelope', '$.context.detail.command')} AS cmd "
        f"FROM events e "
        f"WHERE e.event_name = 'DataLossDetected' "
        f"  AND e.created_at >= {now_sql(offset_days=-30)} "
        f"  AND NOT EXISTS ( "
        f"    SELECT 1 FROM migration_audit m "
        f"    WHERE {audit_window_seconds} <= 3600 "
        f"  ) "
        f"ORDER BY e.created_at DESC LIMIT 10",
    )
    for row in unmatched:
        cmd = str(row["cmd"] or "")[:120]
        issues.append(
            f"- DataLossDetected @ {row['created_at']}: "
            f"no migration_audit row within +-1h. command: {cmd}"
        )

    # 2. Exception fingerprints with no rationale recorded
    thin_fingerprints = query_rows(
        conn,
        "SELECT id, migration_name, started_at, "
        "       COALESCE(exception_reason, '') AS note "
        "FROM migration_audit "
        "WHERE state = 'completed' "
        "  AND migration_name IN ( "
        "    'events-schema-rebuild', 'events-prune', "
        "    'events-legacy-backfill-rewrite', 'events-envelope-repair' "
        "  ) "
        "  AND (COALESCE(exception_reason, '') = '' "
        "       OR LENGTH(COALESCE(exception_reason, '')) < 20) "
        "ORDER BY id DESC LIMIT 10",
    )
    for row in thin_fingerprints:
        issues.append(
            f"- migration_audit #{row['id']} ({row['migration_name']}) "
            f"@ {row['started_at']}: exception fingerprint is missing a "
            "rationale note — expected documented safety exception."
        )

    if issues:
        rec.record(
            "HC-events-destructive-maintenance-audit",
            "Destructive maintenance audit evidence",
            "WARN", "\n".join(issues),
        )
    else:
        rec.record(
            "HC-events-destructive-maintenance-audit",
            "Destructive maintenance audit evidence",
            "PASS", "",
        )
