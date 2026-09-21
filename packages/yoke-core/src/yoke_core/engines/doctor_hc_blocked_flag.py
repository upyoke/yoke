"""doctor health checks for the items.blocked flag model.

Two checks:

- ``HC-blocked-status-drift`` — FAIL when any row holds the legacy
  ``status='blocked'`` value after the migration. Post-cutover, the
  flag-driven model is canonical; any legacy lifecycle-position
  ``blocked`` is drift that must be repaired.
- ``HC-blocked-flag-consistency`` — FAIL when ``blocked=1`` but
  ``blocked_reason`` is empty, when ``blocked=0`` but ``blocked_reason``
  is non-empty, or when ``blocked=1`` and every live hard-block
  dependency is already satisfied (the flag survived a discharged wait).
"""

from __future__ import annotations

from typing import List

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.item_dependency import HARD_BLOCK_GATE_POINTS
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.schema_common import _table_exists
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def hc_blocked_status_drift(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """post-cutover, no row should hold status='blocked'."""
    fails: List[str] = []
    rows = query_rows(
        conn,
        "SELECT id, blocked, blocked_reason FROM items WHERE status='blocked'",
    )
    for row in rows:
        public_ref = render_item_ref(conn, int(row["id"]))
        if row["blocked"] == 1:
            fails.append(
                f"- {public_ref}: status='blocked' AND blocked=1 (drift "
                "from legacy status — migrate via yoke items block / repair)"
            )
        else:
            fails.append(
                f"- {public_ref}: status='blocked' but blocked=0 "
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
    """blocked flag, reason, and discharged hard-block waits must agree."""
    fails: List[str] = []
    missing_reason = query_rows(
        conn,
        "SELECT id FROM items WHERE blocked = 1 AND "
        "(blocked_reason IS NULL OR TRIM(blocked_reason) = '')",
    )
    for row in missing_reason:
        fails.append(
            f"- {render_item_ref(conn, int(row['id']))}: blocked=1 with no "
            "blocked_reason (operator context is required so unblock has "
            "actionable history)"
        )
    stale_reason = query_rows(
        conn,
        "SELECT id, blocked_reason FROM items "
        "WHERE (blocked = 0 OR blocked IS NULL) "
        "AND blocked_reason IS NOT NULL AND TRIM(blocked_reason) <> ''",
    )
    for row in stale_reason:
        fails.append(
            f"- {render_item_ref(conn, int(row['id']))}: blocked=0 with "
            "stale blocked_reason "
            f"({row['blocked_reason']!r}) — unblock should have cleared it"
        )
    fails.extend(_leftover_flag_findings(conn))
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


def _leftover_flag_findings(conn) -> List[str]:
    """FAIL blocked=1 rows whose every live hard-block edge is satisfied."""
    if not _table_exists(conn, "item_dependencies"):
        return []
    from yoke_core.domain.check_hard_blocks import evaluate_blockers

    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    placeholders = ", ".join(marker for _ in HARD_BLOCK_GATE_POINTS)
    rows = query_rows(
        conn,
        "SELECT DISTINCT i.id FROM items i "
        "JOIN item_dependencies d ON d.dependent_item_id = i.id "
        f"WHERE i.blocked = 1 AND d.gate_point IN ({placeholders}) "
        "ORDER BY i.id",
        tuple(sorted(HARD_BLOCK_GATE_POINTS)),
    )
    findings: List[str] = []
    for row in rows:
        item_id = int(row["id"])
        ref = render_item_ref(conn, item_id)
        try:
            unsatisfied = evaluate_blockers(item_id, conn=conn)
        except Exception as exc:  # noqa: BLE001 - leftover flag must not hide
            findings.append(
                f"- {ref}: blocked=1 with live hard-block edges that "
                f"could not be evaluated ({exc})"
            )
            continue
        hard = [
            line for line in unsatisfied
            if _gate_point(line) in HARD_BLOCK_GATE_POINTS
        ]
        if not hard:
            findings.append(
                f"- {ref}: blocked=1 while every live hard-block "
                "dependency is satisfied — clear the flag with "
                "`yoke items unblock`; the edge already carries the wait"
            )
    return findings


def _gate_point(line: str) -> str:
    parts = line.split("|")
    return parts[4] if len(parts) > 4 else ""


__all__ = ["hc_blocked_status_drift", "hc_blocked_flag_consistency"]
