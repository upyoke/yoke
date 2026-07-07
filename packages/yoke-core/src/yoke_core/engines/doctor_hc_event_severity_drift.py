"""Doctor HC: ``events.severity`` canonical-token drift.

The canonical enum is ``yoke_core.domain.events_crud.VALID_SEVERITIES``;
the writer guard normalizes warning-like inputs, and the HC scans
``events.severity`` for any value outside ``VALID_SEVERITIES``.

Outcomes:

* **PASS** — ``events`` table absent (validation surface) or zero
  non-canonical severity rows.
* **FAIL** — one or more rows carry a non-canonical severity literal.
      Detail names per-literal counts plus up to five sample event ids when
      the validation surface exposes the needed columns; the HC also names
      the most recent completed severity-normalization migration when one
      is recorded, so the operator sees which slice owned the cleanup.
* **SKIP** — sqlite read against ``events`` raised an OperationalError
  (defensive guard for partial validation surfaces).
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.events_crud import VALID_SEVERITIES
from yoke_core.domain.schema_common import _table_exists
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

HC_ID = "event-severity-drift"
HC_NAME = "Historical event-severity drift"
_MIGRATION_NAMES = (
    "normalize_warning_event_severity",
    "normalize-event-severity-casing",
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _events_table_present(conn: Any) -> bool:
    return _table_exists(conn, "events")


def _non_canonical_counts(
    conn: Any,
) -> List[Tuple[str, int]]:
    p = _p(conn)
    placeholders = ",".join(p for _ in VALID_SEVERITIES)
    cursor = conn.execute(
        f"SELECT severity, COUNT(*) FROM events "
        f"WHERE severity NOT IN ({placeholders}) "
        f"GROUP BY severity ORDER BY 2 DESC",
        tuple(VALID_SEVERITIES),
    )
    return [(str(row[0]), int(row[1])) for row in cursor.fetchall()]


def _sample_event_ids(
    conn: Any, limit: int = 5
) -> List[Tuple[str, str, str]]:
    p = _p(conn)
    placeholders = ",".join(p for _ in VALID_SEVERITIES)
    cursor = conn.execute(
        f"SELECT event_id, severity, created_at FROM events "
        f"WHERE severity NOT IN ({placeholders}) "
        f"ORDER BY created_at DESC LIMIT {p}",
        (*VALID_SEVERITIES, limit),
    )
    return [
        (str(row[0]), str(row[1]), str(row[2])) for row in cursor.fetchall()
    ]


def _most_recent_severity_migration(
    conn: Any,
) -> Optional[Tuple[str, str]]:
    """Return ``(migration_name, completed_at)`` for the most recently
    completed severity-normalization migration, or ``None`` when no
    completed row exists. Defensive against the validation surface
    that may lack ``migration_audit``."""
    try:
        p = _p(conn)
        placeholders = ",".join(p for _ in _MIGRATION_NAMES)
        row = conn.execute(
            f"SELECT migration_name, completed_at FROM migration_audit "
            f"WHERE migration_name IN ({placeholders}) "
            f"AND state = 'completed' "
            f"ORDER BY completed_at DESC LIMIT 1",
            _MIGRATION_NAMES,
        ).fetchone()
    except db_backend.operational_error_types(conn):
        return None
    if row is None:
        return None
    name = str(row[0])
    completed_at = str(row[1]) if row[1] else ""
    return name, completed_at


def hc_event_severity_drift(
    conn: Any, args: DoctorArgs, rec: RecordCollector
) -> None:
    if not _events_table_present(conn):
        rec.record(
            f"HC-{HC_ID}",
            HC_NAME,
            "PASS",
            "events table absent (validation surface); no drift to scan.",
        )
        return

    try:
        counts = _non_canonical_counts(conn)
    except db_backend.operational_error_types(conn) as exc:
        rec.record(
            f"HC-{HC_ID}",
            HC_NAME,
            "SKIP",
            f"events read failed: {exc}",
        )
        return

    if not counts:
        rec.record(
            f"HC-{HC_ID}",
            HC_NAME,
            "PASS",
            "All events.severity rows use canonical "
            f"VALID_SEVERITIES tokens ({', '.join(VALID_SEVERITIES)}).",
        )
        return

    total = sum(count for _, count in counts)
    per_literal = ", ".join(f"{literal}={count}" for literal, count in counts)
    try:
        samples = _sample_event_ids(conn)
    except db_backend.operational_error_types(conn):
        samples = []
    lines = [
        f"{total} events row(s) carry non-canonical severity literals: "
        f"{per_literal}. Canonical tokens: "
        f"{', '.join(VALID_SEVERITIES)}.",
    ]
    audit = _most_recent_severity_migration(conn)
    if audit is not None:
        migration_name, completed_at = audit
        suffix = f" (completed_at={completed_at})" if completed_at else ""
        lines.append(
            f"Most recent severity-normalization migration: "
            f"{migration_name}{suffix}."
        )
    if samples:
        lines.append("Sample rows:")
        for event_id, severity, created_at in samples:
            lines.append(
                f"- event_id={event_id} severity={severity} "
                f"created_at={created_at}"
            )
    rec.record(f"HC-{HC_ID}", HC_NAME, "FAIL", "\n".join(lines))


__all__ = ["HC_ID", "HC_NAME", "hc_event_severity_drift"]
