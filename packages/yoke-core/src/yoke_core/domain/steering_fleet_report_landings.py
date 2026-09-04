"""Live queue-entry facts for open landings in a fleet report."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain import db_backend
from yoke_core.domain.conflict_survey_declared_paths import TERMINAL_STATUSES
from yoke_core.domain.merge_queue_readiness import (
    MergeQueueReadiness,
    read_merge_queue_readiness,
)
from yoke_core.domain.schema_common import _column_exists
from yoke_core.domain.session_message_types import row_dict
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext


@dataclass(frozen=True)
class FleetLandingReadback:
    """One item row joined to its live GitHub landing facts."""

    item_id: int
    public_ref: str
    status: str
    readiness: MergeQueueReadiness

    @property
    def needs_action(self) -> bool:
        return self.readiness.needs_action

    def to_dict(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "public_ref": self.public_ref,
            "status": self.status,
            **self.readiness.to_dict(),
            "needs_action": self.needs_action,
        }


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _candidates(conn: Any, *, project_id: int) -> list[dict[str, Any]]:
    if not _column_exists(conn, "items", "merge_queue_pr_number"):
        return []
    marker = _marker(conn)
    terminal = tuple(sorted(TERMINAL_STATUSES))
    terminal_slots = ",".join(marker for _ in terminal)
    rows = conn.execute(
        "SELECT i.id, i.project_sequence, i.status, "
        "i.merge_queue_pr_number, i.merge_queue_enqueued_at, "
        "p.slug, p.public_item_prefix, "
        "p.default_branch FROM items i JOIN projects p ON p.id=i.project_id "
        f"WHERE i.project_id={marker} "
        "AND i.merge_queue_pr_number IS NOT NULL "
        "AND i.merge_queue_landed_at IS NULL "
        f"AND i.status NOT IN ({terminal_slots}) ORDER BY i.id",
        (int(project_id), *terminal),
    ).fetchall()
    return [row_dict(row) for row in rows]


def landing_readbacks(
    conn: Any,
    *,
    project_id: int,
    members: Optional[set[int]] = None,
    in_flight_item_ids: frozenset[int] = frozenset(),
) -> tuple[FleetLandingReadback, ...]:
    """Read admitted handoffs and inline waits in the seat's item scope."""
    result: list[FleetLandingReadback] = []
    for row in _candidates(conn, project_id=project_id):
        item_id = int(row["id"])
        if members is not None and item_id not in members:
            continue
        if not row.get("merge_queue_enqueued_at") and item_id not in in_flight_item_ids:
            # The PR is opened during verification, before landing starts. It
            # becomes a fleet landing only when a handoff records admission or
            # a live inline merge wait proves the landing call is in progress.
            continue
        target = str(row.get("default_branch") or "main")
        ctx = MergeContext(
            args=MergeArgs(branch="", target=target),
            project=str(row["slug"]),
        )
        readiness = read_merge_queue_readiness(
            ctx,
            pr_number=str(row["merge_queue_pr_number"]),
            target=target,
        )
        result.append(
            FleetLandingReadback(
                item_id=item_id,
                public_ref=format_item_ref(
                    row["slug"],
                    row["public_item_prefix"],
                    row["project_sequence"],
                    item_id=item_id,
                ),
                status=str(row["status"]),
                readiness=readiness,
            )
        )
    return tuple(result)


def landing_lines(rows: tuple[FleetLandingReadback, ...]) -> list[str]:
    """Render both healthy in-flight and stopped landing facts."""
    return [
        f"  {'!' if row.needs_action else ' '} {row.public_ref}  "
        f"{row.status}  {row.readiness.describe()}"
        + (
            f"; warnings={' | '.join(row.readiness.warnings)}"
            if row.readiness.warnings
            else ""
        )
        for row in rows
    ]


__all__ = [
    "FleetLandingReadback",
    "landing_lines",
    "landing_readbacks",
]
