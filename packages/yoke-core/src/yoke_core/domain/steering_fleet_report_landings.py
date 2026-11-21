"""Recorded landings and live queue-entry facts for the fleet report."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from yoke_contracts.public_ref import format_item_ref
from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_core.domain.steering_report_handler_timing import time_dependency
from yoke_core.domain import db_backend, item_merge_receipt_document
from yoke_core.domain.workflow_status_queries import exclude_terminal_items
from yoke_core.domain.merge_landing_state import PrLandingState
from yoke_core.domain.merge_queue_readiness import (
    MergeQueueReadiness,
    classify_readiness,
    read_merge_queue_readiness,
)
from yoke_core.domain.steering_fleet_report_reads import FleetReportReads
from yoke_core.domain.schema_common import _column_exists
from yoke_core.domain.session_message_types import row_dict
from yoke_core.domain.merge_context import MergeArgs, MergeContext


@dataclass(frozen=True)
class FleetLandingReadback:
    """One item row joined to its recorded or live landing facts."""

    item_id: int
    public_ref: str
    status: str
    readiness: MergeQueueReadiness
    wake_delivered: bool = False
    call_starting: bool = False

    @property
    def needs_action(self) -> bool:
        return not self.call_starting and self.readiness.needs_action

    @property
    def narrative(self) -> str:
        if self.call_starting:
            return f"pull request {self.readiness.pr_number}: landing call starting"
        return self.readiness.describe()

    def to_dict(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "public_ref": self.public_ref,
            "status": self.status,
            "wake_delivered": self.wake_delivered,
            **self.readiness.to_dict(),
            "needs_action": self.needs_action,
            "narrative": self.narrative,
        }


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _candidates(conn: Any, *, project_id: int) -> list[dict[str, Any]]:
    if not _column_exists(conn, "items", "merge_queue_pr_number"):
        return []
    marker = _marker(conn)
    terminal_filter, terminal_params = exclude_terminal_items(conn)
    # An open re-land attempt is the item's landing in flight; the current
    # landing it would replace is already delivered and is not shown.
    rows = conn.execute(
        "SELECT i.id, i.project_sequence, i.status, "
        "COALESCE(a.pr_number, i.merge_queue_pr_number) AS merge_queue_pr_number, "
        "CASE WHEN a.item_id IS NULL THEN i.merge_queue_enqueued_at "
        "ELSE a.enqueued_at END AS merge_queue_enqueued_at, "
        "CASE WHEN a.item_id IS NULL THEN i.merge_queue_notified_at END "
        "AS merge_queue_notified_at, "
        "CASE WHEN a.item_id IS NULL THEN i.merge_queue_landed_at END "
        "AS merge_queue_landed_at, "
        "p.slug, p.public_item_prefix, "
        "p.default_branch FROM items i JOIN projects p ON p.id=i.project_id "
        "LEFT JOIN merge_queue_landing_attempts a "
        "ON a.item_id=i.id AND a.closed_at IS NULL "
        f"WHERE i.project_id={marker} "
        "AND (a.item_id IS NOT NULL OR (i.merge_queue_pr_number IS NOT NULL "
        "AND (i.merge_queue_landed_at IS NULL OR i.merge_queue_notified_at IS NULL))) "
        f"{terminal_filter} ORDER BY i.id",
        (int(project_id), *terminal_params),
    ).fetchall()
    return [row_dict(row) for row in rows]


def _recorded_landing(conn: Any, item_id: int, landed_at: Any) -> PrLandingState:
    entries = item_merge_receipt_document.read_entries(conn, item_id)
    try:
        receipt = next(iter(item_merge_receipt_document.newest_first(entries)), {})
    except InvalidInstant:
        receipt = {}
    head_sha, merge_sha = receipt.get("commit_sha"), receipt.get("merge_sha")
    if not all(
        isinstance(sha, str) and re.fullmatch(r"[0-9a-fA-F]{40}", sha)
        for sha in (head_sha, merge_sha)
    ):
        head_sha = merge_sha = ""
    return PrLandingState(
        merged=True,
        closed=True,
        auto_merge_active=False,
        merged_at=parse_instant(landed_at),
        head_sha=head_sha,
        merge_commit_sha=merge_sha,
    )


@time_dependency("landing_reads")
def landing_readbacks(
    conn: Any,
    *,
    project_id: int,
    members: Optional[set[int]] = None,
    in_flight_item_ids: frozenset[int] = frozenset(),
    reads: Optional[FleetReportReads] = None,
) -> tuple[FleetLandingReadback, ...]:
    """Read admitted handoffs and inline waits in the seat's item scope.

    ``reads`` is the request this readback belongs to: the project's open
    landing rows are read once for it. Stamped landings use their receipts.
    Each unresolved PR's landing, queue entry and checks share one memoized
    GitHub projection.
    """
    request = reads if reads is not None else FleetReportReads()
    result: list[FleetLandingReadback] = []
    candidates = request.cached(
        ("landing_candidates", int(project_id)),
        lambda: _candidates(conn, project_id=project_id),
    )
    for row in candidates:
        item_id = int(row["id"])
        if members is not None and item_id not in members:
            continue
        if not row.get("merge_queue_enqueued_at") and item_id not in in_flight_item_ids:
            # The PR is opened during verification, before landing starts. It
            # becomes a fleet landing only when a handoff records admission or
            # a live inline merge wait proves the landing call is in progress.
            continue
        target = str(row.get("default_branch") or "main")
        pr_number = str(row["merge_queue_pr_number"])
        if landed_at := row["merge_queue_landed_at"]:
            readiness = request.cached(
                ("recorded_landing", item_id),
                lambda: classify_readiness(
                    pr_number=pr_number,
                    target=target,
                    state=_recorded_landing(conn, item_id, landed_at),
                ),
            )
        else:
            ctx = MergeContext(
                args=MergeArgs(branch="", target=target),
                project=str(row["slug"]),
            )
            readiness = read_merge_queue_readiness(
                ctx, pr_number=pr_number, target=target, reads=request.landings
            )
        result.append(
            FleetLandingReadback(
                item_id=item_id,
                public_ref=format_item_ref(
                    row["slug"], row["public_item_prefix"], row["project_sequence"]
                ),
                status=str(row["status"]),
                readiness=readiness,
                wake_delivered=bool(row.get("merge_queue_notified_at")),
                call_starting=not row.get("merge_queue_enqueued_at"),
            )
        )
    return tuple(result)


def landing_wait_pending(row: Mapping[str, Any]) -> bool:
    """Only a healthy open or queued PR excuses holder silence."""
    return row.get("wake_delivered") is False and (
        row.get("in_flight") is True
        and row.get("closed") is False
        and row.get("merged") is False
        and not row.get("failed_checks")
    )


def seat_landing_readbacks(
    conn: Any,
    *,
    project_ids: Sequence[int],
    members: Optional[set[int]],
    in_flight: Sequence[Any],
    reads: FleetReportReads,
) -> tuple[FleetLandingReadback, ...]:
    """One scoped readback set for the idle filter and rendered report."""
    merging = frozenset(call.item_id for call in in_flight if "merge" in call.command)
    return tuple(
        row
        for project_id in project_ids
        for row in landing_readbacks(
            conn,
            project_id=project_id,
            members=members,
            in_flight_item_ids=merging,
            reads=reads,
        )
    )


def landing_lines(rows: tuple[FleetLandingReadback, ...]) -> list[str]:
    """Render both healthy in-flight and stopped landing facts."""
    return [
        f"  {'!' if row.needs_action else ' '} {row.public_ref}  "
        f"{row.status}  {row.narrative}"
        + (
            f"; warnings={' | '.join(row.readiness.warnings)}"
            if row.readiness.warnings and not row.call_starting
            else ""
        )
        for row in rows
    ]


__all__ = [
    "FleetLandingReadback",
    "landing_lines",
    "landing_readbacks",
]
