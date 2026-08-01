"""Synthetic event contamination health check.

Counts test-derived rows that leaked into the canonical events ledger,
separating them from intentionally tagged smoke rows and legitimate
sentinel/backfill lineage.
"""

from __future__ import annotations

from yoke_core.domain.db_helpers import query_rows, query_scalar

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


# ---------------------------------------------------------------------------
# Synthetic event contamination check
# ---------------------------------------------------------------------------

SYNTHETIC_SENTINEL_SESSIONS = (
    "unknown",
    "migration-zero-legacy",
    "status-events-backfill",
)


def hc_synthetic_event_contamination(
    conn, args: DoctorArgs, rec: RecordCollector
) -> None:
    """HC-synthetic-event-contamination: Synthetic rows in the canonical ledger."""
    if not _base._table_exists(conn, "events"):
        rec.record(
            "HC-synthetic-event-contamination",
            "Synthetic event contamination",
            "PASS",
            "events table not present, skipping",
        )
        return

    # Contamination patterns: test-derived session IDs that escape the
    # production-session shape.  Both prefix filters and the ``dup`` fixture
    # are covered here — the stable machine-readable ``synthetic_smoke`` tag
    # from ``anomaly_flags`` is ALSO counted as intentional smoke lineage
    # (not contamination) so doctor never nags about documented exceptions.
    total_row = query_scalar(conn, "SELECT COUNT(*) FROM events")
    total = int(total_row) if total_row else 0
    if total == 0:
        rec.record(
            "HC-synthetic-event-contamination",
            "Synthetic event contamination",
            "PASS",
            "events table empty",
        )
        return

    # deliberate case-sensitive match against internal
    # session_id prefixes and anomaly_flag tokens
    contamination_sql = (
        "SELECT COUNT(*) FROM events "
        "WHERE (session_id LIKE 'test-%%' "
        "   OR session_id LIKE 'sess-%%' "
        "   OR session_id = 'dup') "
        "AND (anomaly_flags IS NULL OR anomaly_flags NOT LIKE '%%synthetic_smoke%%')"
    )
    contaminated_row = query_scalar(conn, contamination_sql)
    contaminated = int(contaminated_row) if contaminated_row else 0

    # Intentional smoke rows — tagged with ``synthetic_smoke`` so they are
    # retained but excluded from contamination counts.
    smoke_row = query_scalar(
        conn,
        # deliberate case-sensitive match against internal anomaly_flag token
        "SELECT COUNT(*) FROM events WHERE anomaly_flags LIKE '%%synthetic_smoke%%'",
    )
    smoke = int(smoke_row) if smoke_row else 0

    # Sentinel / backfill lineage is legitimate historical data.  It is
    # reported separately so the operator can tell "real history" apart
    # from "leaked synthetic telemetry".
    placeholders = ",".join(["%s"] * len(SYNTHETIC_SENTINEL_SESSIONS))
    sentinel_row = query_scalar(
        conn,
        f"SELECT COUNT(*) FROM events WHERE session_id IN ({placeholders})",
        SYNTHETIC_SENTINEL_SESSIONS,
    )
    sentinel = int(sentinel_row) if sentinel_row else 0

    if contaminated == 0:
        detail_parts = [
            f"canonical ledger is clean (0 synthetic rows / {total} total)",
            f"intentional smoke rows (anomaly_flags~'synthetic_smoke'): {smoke}",
            f"historical sentinel/backfill rows: {sentinel}",
        ]
        rec.record(
            "HC-synthetic-event-contamination",
            "Synthetic event contamination",
            "PASS",
            " | ".join(detail_parts),
        )
        return

    # Break down contamination by event_name so the operator can see which
    # emission paths are still leaking.
    top_offenders = query_rows(
        conn,
        # deliberate case-sensitive match against internal
        # session_id prefixes and anomaly_flag tokens
        "SELECT event_name, COUNT(*) AS cnt FROM events "
        "WHERE (session_id LIKE 'test-%%' "
        "   OR session_id LIKE 'sess-%%' "
        "   OR session_id = 'dup') "
        "AND (anomaly_flags IS NULL OR anomaly_flags NOT LIKE '%%synthetic_smoke%%') "
        "GROUP BY event_name ORDER BY cnt DESC LIMIT 10",
    )

    pct = (contaminated / total) * 100.0 if total else 0.0
    lines = [
        f"{contaminated} synthetic rows leaked into canonical ledger "
        f"({pct:.2f}% of {total} total).",
        f"Intentional smoke rows (tagged synthetic_smoke): {smoke}",
        f"Legitimate sentinel/backfill rows (not counted): {sentinel}",
        "Top offending event_names:",
    ]
    for row in top_offenders:
        lines.append(f"- {row['event_name']}: {row['cnt']}")
    lines.append(
        "Cleanup: see docs/event-contract.md section 6 "
        "'Synthetic-Row Cleanup Guidance' before deleting rows — the "
        "sentinel session IDs above are legitimate history."
    )

    rec.record(
        "HC-synthetic-event-contamination",
        "Synthetic event contamination",
        "WARN",
        "\n".join(lines),
    )
