"""Compatibility surface for frontier computation."""

from __future__ import annotations

from .frontier_classify import (
    _EPIC_ADAPTER_MAP,
    _STATUS_ADAPTER_MAP,
    classify_next_action,
)
from .frontier_compute import compute_frontier
from .frontier_depth import _compute_downstream_depths
from .frontier_rank import rank_frontier
from .frontier_types import AdapterCategory, FrontierItem, FrontierResult

__all__ = [
    "AdapterCategory",
    "FrontierItem",
    "FrontierResult",
    "classify_next_action",
    "rank_frontier",
    "compute_frontier",
]
