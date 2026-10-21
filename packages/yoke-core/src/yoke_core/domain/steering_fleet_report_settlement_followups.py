"""The steering report's failed QA settlement follow-up section.

A waiver owes its member's close-out replay
(:mod:`yoke_core.domain.qa_settlement_followups`), and control-plane upkeep
retries a replay that raised, keeping the error on its row. A row that keeps
failing never clears on its own, so each one prints here with its item and
error until a replay succeeds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain.project_identity import row_value
from yoke_core.domain.steering_fleet_report_render_text import SECTION_LIMIT, capped

HEADING = (
    "failed QA settlement follow-ups — a waiver's close-out replay raised; "
    "upkeep retries it every minute"
)
RECOVERY = (
    "fix the cause the error names; the next retry clears the row. "
    'Every owed row: yoke db read "SELECT * FROM qa_settlement_followups"'
)


@dataclass(frozen=True)
class FailedSettlementFollowup:
    item_id: int
    public_ref: str
    attempts: int
    last_error: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "public_ref": self.public_ref,
            "attempts": self.attempts,
            "last_error": self.last_error,
        }


def failed_settlement_followups(
    conn: Any, *, project_id: int
) -> tuple[FailedSettlementFollowup, ...]:
    """This project's owed follow-ups whose last replay raised."""
    rows = conn.execute(
        "SELECT f.item_id, f.attempts, f.last_error, i.project_sequence, "
        "p.public_item_prefix AS prefix "
        "FROM qa_settlement_followups f "
        "JOIN items i ON i.id = f.item_id "
        "JOIN projects p ON p.id = i.project_id "
        "WHERE i.project_id = %s AND f.last_error <> '' "
        "ORDER BY f.item_id",
        (int(project_id),),
    ).fetchall()
    return tuple(
        FailedSettlementFollowup(
            item_id=int(row_value(row, "item_id", 0)),
            public_ref=format_item_ref(
                None,
                row_value(row, "prefix", 4),
                row_value(row, "project_sequence", 3),
            ),
            attempts=int(row_value(row, "attempts", 1) or 0),
            last_error=str(row_value(row, "last_error", 2) or ""),
        )
        for row in rows
    )


def settlement_followup_section(report: Any) -> list[str]:
    """The section, heading and recovery included; empty when none failed."""
    rows: tuple[FailedSettlementFollowup, ...] = getattr(
        report, "settlement_followups", ()
    )
    if not rows:
        return []
    lines = [
        f"  {row.public_ref} after {row.attempts} attempt(s): {row.last_error}"
        for row in rows[:SECTION_LIMIT]
    ]
    return [f"{HEADING}:", *capped(lines, len(rows)), f"  recovery: {RECOVERY}"]


def settlement_followup_fingerprint(report: Any) -> list[Any]:
    """Which items are failing, with what error; blind to the attempt count."""
    return sorted(
        (row.public_ref, row.last_error)
        for row in getattr(report, "settlement_followups", ())
    )


__all__ = [
    "FailedSettlementFollowup",
    "HEADING",
    "failed_settlement_followups",
    "settlement_followup_fingerprint",
    "settlement_followup_section",
]
