"""The steering report's failed scheduled universe prune section.

Control-plane upkeep runs universe row retention on a schedule and keeps a
receipt for each run (:mod:`yoke_core.domain.universe_prune_schedule`). When
the latest run stopped on a refusal, every project's report prints it with
its code, reason and recovery until a later run succeeds: retention is
universe-wide, so the failure belongs to every steering scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from yoke_contracts.timestamps import format_instant
from yoke_core.domain.universe_prune_receipt_schema import OUTCOME_FAILED
from yoke_core.domain.universe_prune_schedule import latest_receipt

HEADING = (
    "failed scheduled universe prune — upkeep's last row-retention run "
    "stopped on a refusal; it retries every 6 hours"
)
READ_RECEIPTS = (
    'Every receipt: yoke db read "SELECT * FROM universe_prune_receipts '
    'ORDER BY started_at DESC LIMIT 10"'
)


@dataclass(frozen=True)
class FailedPrune:
    started_at: datetime
    code: str
    reason: str
    recovery: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": format_instant(self.started_at),
            "code": self.code,
            "reason": self.reason,
            "recovery": self.recovery,
        }


def failed_prunes(conn: Any) -> tuple[FailedPrune, ...]:
    """The latest scheduled prune when it failed; empty otherwise."""
    latest = latest_receipt(conn)
    if latest is None or latest.outcome != OUTCOME_FAILED:
        return ()
    return (
        FailedPrune(
            started_at=latest.started_at,
            code=latest.failure_code,
            reason=latest.failure_reason,
            recovery=latest.failure_recovery,
        ),
    )


def failed_prune_section(report: Any) -> list[str]:
    """The section, heading and recovery included; empty when none failed."""
    lines = [f"{HEADING}:"]
    for row in getattr(report, "failed_prunes", ()):
        lines += [
            f"  {row.code} at {format_instant(row.started_at)}: {row.reason}",
            f"  recovery: {row.recovery} {READ_RECEIPTS}",
        ]
    return lines if len(lines) > 1 else []


def failed_prune_fingerprint(report: Any) -> list[Any]:
    """Which refusal is current; blind to when the retry ran."""
    return sorted((row.code, row.reason) for row in getattr(report, "failed_prunes", ()))


__all__ = [
    "FailedPrune",
    "HEADING",
    "failed_prune_fingerprint",
    "failed_prune_section",
    "failed_prunes",
]
