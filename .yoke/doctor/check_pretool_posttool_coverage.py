"""HC-pretool-posttool-coverage — PreToolUse must not trail PostToolUse.

A surface whose PostToolUse count materially exceeds its PreToolUse count
is running tools without the guardrail chain. Denies make Pre run slightly
ahead of Post; inversion is the Cursor dual-config signature (matcherless
Post catch-all, matcher-gated Pre). Tools that emit neither event (Cursor
Glob / MCP-style calls) are a declared harness gap and sit outside this
count.
"""

from __future__ import annotations

from typing import Any, List, Tuple

from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.time_sql import now_sql
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_project_checks._declare import self_project_checks


HC_SLUG = "HC-pretool-posttool-coverage"
HC_LABEL = "PreToolUse coverage must not fall below PostToolUse per surface"
_LOOKBACK_HOURS = 24
_MIN_POST = 30
# Fail when pre < 90% of post (integer: pre * 10 < post * 9).
_RATIO_NUM = 9
_RATIO_DEN = 10


def coverage_inverts(pre_n: int, post_n: int) -> bool:
    """True when a sampled surface's Pre count trails Post beyond tolerance."""
    if post_n < _MIN_POST:
        return False
    return pre_n * _RATIO_DEN < post_n * _RATIO_NUM


def _coverage_rows(conn: Any) -> List[Tuple[str, int, int]] | None:
    if not _table_exists(conn, "events") or not _table_exists(conn, "harness_sessions"):
        return None
    if not _column_exists(conn, "events", "hook_event_name"):
        return None
    if not _column_exists(conn, "harness_sessions", "executor_surface"):
        return None
    cutoff = now_sql(offset_hours=-_LOOKBACK_HOURS)
    rows = conn.execute(
        f"""
        SELECT COALESCE(s.executor_surface, ''),
               SUM(CASE WHEN e.hook_event_name = 'PreToolUse' THEN 1 ELSE 0 END),
               SUM(CASE WHEN e.hook_event_name = 'PostToolUse' THEN 1 ELSE 0 END)
        FROM events e
        JOIN harness_sessions s ON s.session_id = e.session_id
        WHERE (e.created_at)::timestamp >= ({cutoff})::timestamp
          AND e.event_name IN (
              'HarnessToolCallStarted', 'HarnessToolCallCompleted'
          )
          AND e.hook_event_name IN ('PreToolUse', 'PostToolUse')
        GROUP BY 1
        """
    ).fetchall()
    return [(str(row[0]), int(row[1] or 0), int(row[2] or 0)) for row in rows]


def hc_pretool_posttool_coverage(
    conn: Any, args: DoctorArgs, rec: RecordCollector,
) -> None:
    rows = _coverage_rows(conn)
    if rows is None:
        rec.record(
            HC_SLUG, HC_LABEL, "PASS",
            "events/session coverage columns not present; skipping",
        )
        return
    inverted = [
        (surface, pre_n, post_n)
        for surface, pre_n, post_n in rows
        if surface and coverage_inverts(pre_n, post_n)
    ]
    if not inverted:
        sampled = [s for s, _pre, post in rows if s and post >= _MIN_POST]
        rec.record(
            HC_SLUG, HC_LABEL, "PASS",
            (
                f"no inversion in {_LOOKBACK_HOURS}h"
                + (f" (surfaces: {', '.join(sampled)})" if sampled else "")
            ),
        )
        return
    lines = [
        f"{surface}: PreToolUse={pre_n} PostToolUse={post_n} "
        f"(Pre is {pre_n / post_n:.0%} of Post)"
        for surface, pre_n, post_n in inverted
    ]
    rec.record(
        HC_SLUG, HC_LABEL, "FAIL",
        "PreToolUse fell materially below PostToolUse; tools on that "
        "surface ran without the guardrail chain. "
        + "; ".join(lines),
    )


PROJECT_HEALTH_CHECKS = self_project_checks(
    (
        "pretool-posttool-coverage",
        "PreToolUse coverage must not fall below PostToolUse per surface",
        hc_pretool_posttool_coverage,
    ),
)


__all__ = [
    "HC_LABEL",
    "HC_SLUG",
    "PROJECT_HEALTH_CHECKS",
    "coverage_inverts",
    "hc_pretool_posttool_coverage",
]
