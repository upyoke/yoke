"""Merge state for delivery diagnostics and dated dependency landing facts.

A ``fact:merged`` edge clears on a recorded landing after the edge was made,
and stays clear only while that landing still stands: when rework returns the
blocker to an earlier stage after it landed, the blocker owes another landing
and the edge waits again until a newer landing stamp is recorded.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_core.domain import db_backend
from yoke_core.domain.dependency_types import GateResult
from yoke_core.domain.schema_common import _get_columns
from yoke_core.domain.session_item_stage_rework import (
    items_returned_after_landing,
    owes_relanding,
)
from yoke_core.domain.workflow_runtime import WorkflowRuntime


def read_returned_after_landing(conn: Any, blocker_ids: Iterable[Any]) -> frozenset[int]:
    """Blockers whose current status was recorded after their latest landing.

    One read per batch; :func:`blocker_owes_relanding` excludes the close-out
    move to release, which is recorded after the landing too.
    """
    wanted = sorted({int(item_id) for item_id in blocker_ids if item_id is not None})
    if conn is None or not wanted:
        return frozenset()
    stamps = [
        column
        for column in ("merged_at", "merge_queue_landed_at")
        if column in set(_get_columns(conn, "items"))
    ]
    if not stamps:
        return frozenset()
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        f"SELECT id,status,{','.join(stamps)} FROM items WHERE id IN ("
        + ",".join(marker for _ in wanted)
        + ")",
        tuple(wanted),
    ).fetchall()
    items = {
        int(row[0]): {"status": row[1], **dict(zip(stamps, row[2:]))} for row in rows
    }
    return frozenset(items_returned_after_landing(conn, items))


def blocker_owes_relanding(
    blocking_status: Optional[str],
    returned_after_landing: bool,
    workflow: WorkflowRuntime,
) -> bool:
    """Rework returned the landed blocker before release; it must land again."""
    return owes_relanding(
        workflow.stage_implies_merge(str(blocking_status or "")),
        returned_after_landing,
    )


def evaluate_recorded_merge(
    merged_at: Any, created_at: Any, *, relanding_owed: bool = False
) -> GateResult:
    """Only a standing recorded landing strictly after this edge clears its wait."""
    if merged_at is None or merged_at == "":
        return GateResult(False, "merge_not_landed: waiting for the blocker to merge.")
    try:
        landed = parse_instant(merged_at)
        created = parse_instant(created_at)
    except InvalidInstant:
        return GateResult(
            False,
            "merge_landing_unverified: the recorded landing time is invalid or the "
            "dependency creation time is missing; record the blocker's next landing "
            "through yoke merge item and inspect the edge with yoke items dependency "
            "list.",
        )
    if landed <= created:
        return GateResult(
            False,
            "merge_landing_predates_dependency: the recorded landing is not after "
            "this edge was created; wait for the blocker's next recorded landing.",
        )
    if relanding_owed:
        return GateResult(
            False,
            "merge_relanding_owed: rework returned the blocker to an earlier stage "
            "after its last landing; wait for its next recorded landing.",
        )
    return GateResult(
        True, "Blocking item's recorded landing is after dependency creation."
    )


def evaluate_merge_state(
    blocking_status: str,
    blocking_worktree: Optional[str],
    blocking_merged: Optional[bool],
    workflow: WorkflowRuntime,
) -> GateResult:
    if blocking_merged is True:
        return GateResult(True, "Blocking item's merge is confirmed.")
    if blocking_merged is False:
        branch = f" ({blocking_worktree})" if blocking_worktree else ""
        return GateResult(
            False, f"Blocking item's branch{branch} is not yet merged to main."
        )
    if workflow.stage_implies_merge(blocking_status):
        return GateResult(
            True,
            f"Blocking item status is '{blocking_status}' (merge inferred).",
        )
    return GateResult(
        False,
        f"Blocking item status is '{blocking_status}'; branch merge not confirmed.",
    )
