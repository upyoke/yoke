"""Open dependency edges that make a carried item's release QA premature."""

from __future__ import annotations

from typing import Any, Sequence

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.dependency_satisfaction import unsatisfied_dependency_pairs
from yoke_core.domain.dependency_types import GateResult
from yoke_core.domain.deployment_qa_source_obligation import latest_completion_run


def unshipped_dependency_pairs(
    conn: Any, item_ids: Sequence[int]
) -> list[tuple[int, int, GateResult]]:
    """Open blocking edges whose blocker has neither completed nor shipped.

    Reuse the dependency kernel's direction, satisfaction and coordination
    rules. A blocker proposed for this same release is still unshipped: QA
    that needs its completed delivery waits for a subsequent release.
    Delivery uses the existing completion-flow membership fact, without a
    repository walk inside composition's database locks.
    """
    shipped: dict[int, bool] = {}
    pending = []
    for dependent, blocker, verdict in unsatisfied_dependency_pairs(conn, item_ids):
        if blocker not in shipped:
            item = query_one(conn, "SELECT status FROM items WHERE id=%s", (blocker,))
            delivery = latest_completion_run(conn, blocker) if item else None
            shipped[blocker] = bool(
                item
                and item["status"] == "done"
                or delivery
                and delivery["status"] == "succeeded"
            )
        if not shipped[blocker]:
            pending.append((dependent, blocker, verdict))
    return pending
