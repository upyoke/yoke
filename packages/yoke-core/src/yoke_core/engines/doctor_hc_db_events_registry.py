"""Event-registry coverage health check.

Owns ``hc_event_registry_coverage`` — the HC that compares ``events``
against ``event_registry`` to surface stale registry entries (active
but not emitted in 30 days, excluding expected low-cadence active events)
and rogue events (emitted but not registered).
"""

from __future__ import annotations

from typing import List

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.populate_registry_data_authoritative import (
    EXPECTED_LOW_CADENCE_ACTIVE,
)
from yoke_core.domain.time_sql import now_sql

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def hc_event_registry_coverage(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-event-registry-coverage: Event registry coverage."""
    if not _base._table_exists(conn, "event_registry"):
        rec.record("HC-event-registry-coverage", "Event registry coverage", "PASS",
                    "event_registry table not present, skipping")
        return

    issues: List[str] = []

    low_cadence_names = tuple(EXPECTED_LOW_CADENCE_ACTIVE)
    low_cadence_clause = ""
    if low_cadence_names:
        placeholders = ",".join(_p(conn) for _ in low_cadence_names)
        low_cadence_clause = f"AND er.event_name NOT IN ({placeholders}) "

    # Stale: registered active entries not emitted in 30 days, unless they are
    # explicitly classified as expected low-cadence active events.
    stale = query_rows(
        conn,
        "SELECT er.event_name FROM event_registry er "
        "WHERE er.status='active' "
        f"{low_cadence_clause}"
        "AND er.event_name NOT IN ("
        "  SELECT DISTINCT ae.event_name FROM events ae "
        f"  WHERE ae.created_at >= {now_sql(offset_days=-30)}"
        ")",
        low_cadence_names,
    )
    if stale:
        issues.append("Stale registry entries (active but not emitted in 30d):")
        for r in stale:
            issues.append(f"- {r['event_name']}")

    # Rogue: emitted in 30 days but not registered
    rogue = query_rows(
        conn,
        "SELECT DISTINCT ae.event_name FROM events ae "
        f"WHERE ae.created_at >= {now_sql(offset_days=-30)} "
        "AND ae.event_name NOT IN (SELECT event_name FROM event_registry)",
    )
    if rogue:
        issues.append("Rogue events (emitted but not registered):")
        for r in rogue:
            issues.append(f"- {r['event_name']}")

    if issues:
        rec.record("HC-event-registry-coverage", "Event registry coverage", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-event-registry-coverage", "Event registry coverage", "PASS", "")
