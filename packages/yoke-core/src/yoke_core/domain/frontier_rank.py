"""Deterministic frontier ranking."""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from .frontier_types import AdapterCategory, FrontierItem
from .lifecycle import progression_index


_PRIORITY_RANK: Dict[str, int] = {
    "high": 0,
    "medium": 1,
    "low": 2,
}


def rank_frontier(items: Sequence[FrontierItem]) -> List[FrontierItem]:
    """Sort frontier items by deterministic priority ranking."""

    def sort_key(item: FrontierItem) -> Tuple:
        nearly_done = 0 if item.adapter == AdapterCategory.USHER else 1
        pri = _PRIORITY_RANK.get(item.priority, 99)
        depth = -item.downstream_depth
        unblocks = -item.unblocks_count
        prog = progression_index(item.status, item_type=item.item_type)
        lifecycle = -(prog if prog is not None else -1)
        return (nearly_done, pri, depth, unblocks, lifecycle, item.created_at)

    return sorted(items, key=sort_key)
