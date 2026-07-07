"""doctor health checks for the items.blocked flag model.

Two checks:

- ``HC-blocked-status-drift`` — FAIL when any row holds the legacy
  ``status='blocked'`` value after the migration. Post-cutover, the
  flag-driven model is canonical; any legacy lifecycle-position
  ``blocked`` is drift that must be repaired.
- ``HC-blocked-flag-consistency`` — FAIL when ``blocked=1`` but
  ``blocked_reason`` is empty (no operator-supplied context for an
  ongoing block) or when ``blocked=0`` but ``blocked_reason`` is
  non-empty (stale reason that survived an unblock).
"""

from __future__ import annotations

from typing import List

from yoke_core.domain.db_helpers import query_rows
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def hc_blocked_status_drift(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """post-cutover, no row should hold status='blocked'."""
    fails: List[str] = []
    rows = query_rows(
        conn,
        "SELECT id, blocked, blocked_reason FROM items WHERE status='blocked'",
    )
    for row in rows:
        item_id = row["id"]
        if row["blocked"] == 1:
            fails.append(
                f"- YOK-{item_id}: status='blocked' AND blocked=1 (drift "
                "from legacy status — migrate via /yoke block / repair)"
            )
        else:
            fails.append(
                f"- YOK-{item_id}: status='blocked' but blocked=0 "
                "(legacy lifecycle position survived without flag — repair "
                "the row to use the flag instead)"
            )
    if fails:
        rec.record(
            "HC-blocked-status-drift",
            "Blocked status drift",
            "FAIL",
            "\n".join(fails),
        )
    else:
        rec.record(
            "HC-blocked-status-drift",
            "Blocked status drift",
            "PASS",
            "",
        )


def hc_blocked_flag_consistency(
    conn, args: DoctorArgs, rec: RecordCollector
) -> None:
    """blocked flag and reason must agree."""
    fails: List[str] = []
    missing_reason = query_rows(
        conn,
        "SELECT id FROM items WHERE blocked = 1 AND "
        "(blocked_reason IS NULL OR TRIM(blocked_reason) = '')",
    )
    for row in missing_reason:
        fails.append(
            f"- YOK-{row['id']}: blocked=1 with no blocked_reason (operator "
            "context is required so unblock has actionable history)"
        )
    stale_reason = query_rows(
        conn,
        "SELECT id, blocked_reason FROM items "
        "WHERE (blocked = 0 OR blocked IS NULL) "
        "AND blocked_reason IS NOT NULL AND TRIM(blocked_reason) <> ''",
    )
    for row in stale_reason:
        fails.append(
            f"- YOK-{row['id']}: blocked=0 with stale blocked_reason "
            f"({row['blocked_reason']!r}) — unblock should have cleared it"
        )
    if fails:
        rec.record(
            "HC-blocked-flag-consistency",
            "Blocked flag consistency",
            "FAIL",
            "\n".join(fails),
        )
    else:
        rec.record(
            "HC-blocked-flag-consistency",
            "Blocked flag consistency",
            "PASS",
            "",
        )


__all__ = ["hc_blocked_status_drift", "hc_blocked_flag_consistency"]
