"""Doctor HC for enum coverage of ``HarnessToolCallDenied`` outcomes.

The hook runner records every guard decision through
:mod:`yoke_core.hooks.guard_denial_record`, whose outcomes are the
:data:`yoke_core.domain.events_tool_call_outcome.OUTCOMES` constants, so no
source scan is needed. This check queries the ``events`` ledger for
``HarnessToolCallDenied`` rows in the last 3 days whose ``event_outcome`` is
not in :data:`OUTCOMES`. A drifted row means a writer outside the recorder
exists, or ``OUTCOMES`` was tightened without sweeping historical rows.

Verdicts:

* **FAIL** — at least one live row carries a non-enum value.
* **PASS** — no drifted rows.
* **SKIP** — the events table is missing (minimal-schema fixture
  install) or the read failed.
"""

from __future__ import annotations

from yoke_core.domain import db_backend
from datetime import timedelta
from typing import Any, List, Tuple

from yoke_core.domain.db_helpers import instant_parameter, utc_now
from yoke_core.domain.events_tool_call_outcome import OUTCOMES
from yoke_core.domain.schema_common import _table_exists
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


HC_ID = "event-outcome-enum-coverage"
HC_NAME = "Tool-call outcome enum coverage for HarnessToolCallDenied emitters"

_TARGET_EVENT_NAME = "HarnessToolCallDenied"


def _live_events_scan(conn: Any) -> List[Tuple[str, str, int]]:
    """Return ``[(event_outcome, sample_event_id, count), ...]`` for any
    ``HarnessToolCallDenied`` rows in the 3-day window whose
    ``event_outcome`` is outside OUTCOMES."""
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    placeholders = ",".join(p for _ in OUTCOMES)
    cutoff = instant_parameter(conn, utc_now() - timedelta(days=3))
    params: Tuple = (_TARGET_EVENT_NAME, *sorted(OUTCOMES), cutoff)
    sql = (
        "SELECT event_outcome, MIN(event_id) AS sample, COUNT(*) AS n "
        "FROM events "
        f"WHERE event_name = {p} "
        f"AND event_outcome NOT IN ({placeholders}) "
        f"AND created_at > {p} "
        "GROUP BY event_outcome ORDER BY n DESC"
    )
    return list(conn.execute(sql, params).fetchall())


def _events_table_exists(conn: Any) -> bool:
    return _table_exists(conn, "events")


def hc_event_outcome_enum_coverage(
    conn: Any, args: DoctorArgs, rec: RecordCollector
) -> None:
    if not _events_table_exists(conn):
        rec.record(
            f"HC-{HC_ID}",
            HC_NAME,
            "SKIP",
            "events table not present on this DB",
        )
        return

    try:
        live_findings = _live_events_scan(conn)
    except db_backend.database_error_types(conn) as exc:
        rec.record(
            f"HC-{HC_ID}",
            HC_NAME,
            "SKIP",
            f"events read failed: {exc}",
        )
        return

    if live_findings:
        lines: List[str] = [
            f"{len(live_findings)} non-enum outcome(s) in the "
            f"last 3 days of HarnessToolCallDenied rows:"
        ]
        for outcome, sample, count in live_findings:
            lines.append(
                f"- outcome={outcome!r} count={count} sample_event_id={sample}"
            )
        rec.record(f"HC-{HC_ID}", HC_NAME, "FAIL", "\n".join(lines))
        return

    rec.record(
        f"HC-{HC_ID}",
        HC_NAME,
        "PASS",
        "No non-enum HarnessToolCallDenied rows in the last 3 days.",
    )


__all__ = ["HC_ID", "HC_NAME", "hc_event_outcome_enum_coverage"]

# Slug and display name are the ones this check has always reported under.
from yoke_project_checks._declare import (  # noqa: E402
    self_project_checks,
)

PROJECT_HEALTH_CHECKS = self_project_checks(
    (
        "event-outcome-enum-coverage",
        "Tool-call outcome enum coverage for HarnessToolCallDenied emitters",
        hc_event_outcome_enum_coverage,
    ),
)
