"""Open dependency edges that make a carried item's release QA premature."""

from __future__ import annotations

from typing import Any, Sequence

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.dependency_satisfaction import unsatisfied_dependency_pairs
from yoke_core.domain.dependency_types import GateResult
from yoke_core.domain.deployment_qa_source_obligation import latest_completion_run


def _delivered(delivery: dict[str, Any] | None) -> bool:
    """Whether an incomplete blocker's holding run finished, for diagnosis.

    This is not dependency satisfaction: the kernel reads completion and its
    persisted environment attribution, independently of current run status.
    """
    return bool(
        delivery and delivery["status"] == "succeeded" and not delivery["settling"]
    )


def unshipped_dependency_pairs(
    conn: Any, item_ids: Sequence[int]
) -> list[tuple[int, int, GateResult]]:
    """Read each edge's declared milestone or completed environment fact.

    Completion alone cannot clear an explicit environment edge, and a run's
    success cannot substitute for an item's done milestone.
    """
    return unsatisfied_dependency_pairs(conn, item_ids)


def blocker_holding_run(conn: Any, blocker_id: int) -> tuple[str, str] | None:
    """The live release still delivering *blocker_id*, as ``(run_id, state)``.

    ``state`` is ``settling`` for a run closing its members, else the run's
    own status. ``None`` when no live release holds the blocker — it has not
    been released yet, or its delivery finished.
    """
    item = query_one(conn, "SELECT status FROM items WHERE id=%s", (int(blocker_id),))
    if item and item["status"] == "done":
        return None
    delivery = latest_completion_run(conn, int(blocker_id), skip_terminal_failures=True)
    if delivery is None or _delivered(delivery):
        return None
    return delivery["id"], "settling" if delivery["settling"] else delivery["status"]


__all__ = ["blocker_holding_run", "unshipped_dependency_pairs"]
