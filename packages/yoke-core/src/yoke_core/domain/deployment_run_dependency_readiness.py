"""Open dependency edges that make a carried item's release QA premature."""

from __future__ import annotations

from typing import Any, Sequence

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.dependency_satisfaction import unsatisfied_dependency_pairs
from yoke_core.domain.dependency_types import GateResult
from yoke_core.domain.deployment_qa_source_obligation import latest_completion_run


def _delivered(delivery: dict[str, Any] | None) -> bool:
    """Whether a completion run recorded its delivery as finished.

    A settling run reads ``succeeded`` to completion authority, but it is
    still ``executing`` on its own row, and the dependency gate counts only a
    recorded ``succeeded`` run. Calling it shipped here would enroll a
    dependent that the same composition's dependency check then refuses.
    """
    return bool(
        delivery and delivery["status"] == "succeeded" and not delivery["settling"]
    )


def unshipped_dependency_pairs(
    conn: Any, item_ids: Sequence[int]
) -> list[tuple[int, int, GateResult]]:
    """Open blocking edges whose blocker has neither completed nor shipped.

    Reuse the dependency kernel's direction, satisfaction and coordination
    rules. A blocker proposed for this same release is still unshipped: QA
    that needs its completed delivery waits for a subsequent release. So is
    a blocker whose release is still live or settling. Delivery uses the
    existing completion-flow membership fact, without a repository walk
    inside composition's database locks.
    """
    shipped: dict[int, bool] = {}
    pending = []
    for dependent, blocker, verdict in unsatisfied_dependency_pairs(conn, item_ids):
        if blocker not in shipped:
            item = query_one(conn, "SELECT status FROM items WHERE id=%s", (blocker,))
            delivery = latest_completion_run(conn, blocker) if item else None
            shipped[blocker] = bool(
                item and item["status"] == "done" or _delivered(delivery)
            )
        if not shipped[blocker]:
            pending.append((dependent, blocker, verdict))
    return pending


def blocker_holding_run(conn: Any, blocker_id: int) -> tuple[str, str] | None:
    """The live release still delivering *blocker_id*, as ``(run_id, state)``.

    ``state`` is ``settling`` for a run closing its members, else the run's
    own status. ``None`` when no live release holds the blocker — it has not
    been released yet, or its delivery finished.
    """
    delivery = latest_completion_run(conn, int(blocker_id), skip_terminal_failures=True)
    if delivery is None or _delivered(delivery):
        return None
    return delivery["id"], "settling" if delivery["settling"] else delivery["status"]


__all__ = ["blocker_holding_run", "unshipped_dependency_pairs"]
