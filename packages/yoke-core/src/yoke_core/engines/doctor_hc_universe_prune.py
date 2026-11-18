"""Doctor: the universe's scheduled row retention keeps running.

Control-plane upkeep prunes disposable universe rows on a schedule and
writes a ``universe_prune_receipts`` row for each run
(:mod:`yoke_core.domain.universe_prune_schedule`). A universe whose last
successful receipt is older than :data:`STALE_AFTER` is not being pruned:
its upkeep host is down, or every run is refusing. A run that left tables
unfinished after repeated statement or lock limits is a warning.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from yoke_contracts.timestamps import format_instant, parse_instant, utc_now
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.universe_prune_receipt_schema import (
    OUTCOME_BUDGET,
    OUTCOME_DRAINED,
    OUTCOME_FAILED,
    UNIVERSE_PRUNE_RECEIPTS_TABLE,
)
from yoke_core.domain.universe_prune_schedule import latest_receipt
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


HC_SLUG = "HC-universe-prune-receipt"
HC_LABEL = "Scheduled universe pruning has a recent receipt"
STALE_AFTER = timedelta(days=2)
RECOVERY = (
    "Upkeep runs inside the API server's health refresh (hosted and "
    "self-hosted) or the machine relay (local): confirm that host is running, "
    "read the newest receipts with "
    '`yoke db read "SELECT * FROM universe_prune_receipts ORDER BY started_at DESC LIMIT 10"`, '
    "fix the refusal they name, or run `yoke universe prune --apply` now."
)


def _universe_created_at(conn: Any):
    row = conn.execute("SELECT MIN(created_at) FROM organizations").fetchone()
    return parse_instant(row[0]) if row and row[0] else None


def hc_universe_prune_receipt(
    conn: Any, args: DoctorArgs, rec: RecordCollector
) -> None:
    """Scheduled universe pruning has a recent receipt."""
    del args
    if not _table_exists(conn, UNIVERSE_PRUNE_RECEIPTS_TABLE):
        rec.record(
            HC_SLUG,
            HC_LABEL,
            "SKIP",
            "universe_prune_receipts is not present on this schema; the "
            "server's next boot converge creates it.",
        )
        return
    now = utc_now()
    success = latest_receipt(conn, outcomes=(OUTCOME_DRAINED, OUTCOME_BUDGET))
    latest = latest_receipt(conn)
    failure = (
        f" Latest run {format_instant(latest.started_at)} failed: "
        f"{latest.failure_code}: {latest.failure_reason}"
        if latest is not None and latest.outcome == OUTCOME_FAILED
        else ""
    )
    if success is None:
        created = _universe_created_at(conn)
        if created is not None and created > now - STALE_AFTER:
            rec.record(
                HC_SLUG,
                HC_LABEL,
                "PASS",
                "No prune receipt yet; this universe is younger than two days." + failure,
            )
            return
        rec.record(
            HC_SLUG,
            HC_LABEL,
            "FAIL",
            "No successful scheduled prune receipt exists." + failure + " " + RECOVERY,
        )
        return
    if success.started_at < now - STALE_AFTER:
        rec.record(
            HC_SLUG,
            HC_LABEL,
            "FAIL",
            "The last successful scheduled prune started "
            f"{format_instant(success.started_at)}, more than two days ago."
            + failure
            + " "
            + RECOVERY,
        )
        return
    if latest is not None and latest.unfinished:
        tables = ", ".join(
            f"{row.get('table')} ({row.get('reason')})" for row in latest.unfinished
        )
        rec.record(
            HC_SLUG,
            HC_LABEL,
            "WARN",
            f"The last scheduled prune left tables unfinished: {tables}. "
            "If it repeats, ask the universe administrator to inspect those "
            "tables' indexes and size.",
        )
        return
    deleted = sum(success.deleted.values())
    rec.record(
        HC_SLUG,
        HC_LABEL,
        "PASS",
        f"Last successful prune {format_instant(success.started_at)} "
        f"({success.outcome}, {deleted:,} rows deleted).",
    )


__all__ = ["HC_LABEL", "HC_SLUG", "STALE_AFTER", "hc_universe_prune_receipt"]
