"""Adapter classification for frontier items.

The ``blocked`` status entry below is preserved for legacy drift only.
After the cutover, the canonical signal is ``items.blocked = 1``,
which ``frontier_compute`` partitions into the blocked list and stamps
with ``AdapterCategory.WAIT`` directly — see
``yoke_core.domain.frontier_compute.compute_frontier``. The ``stopped``
and ``failed`` entries are unchanged: they are exceptional lifecycle
positions handled by the scheduler's exceptional-items path.
"""

from __future__ import annotations

from typing import Dict

from .frontier_types import AdapterCategory
from .lifecycle import is_valid_item_status


_STATUS_ADAPTER_MAP: Dict[str, AdapterCategory] = {
    "idea": AdapterCategory.SHEPHERD,
    "planned": AdapterCategory.SHEPHERD,
    "planning": AdapterCategory.SHEPHERD,
    "plan-drafted": AdapterCategory.REFINE,
    "refining-plan": AdapterCategory.REFINE,
    "release": AdapterCategory.USHER,
    "done": AdapterCategory.SKIP,
    "refining-idea": AdapterCategory.REFINE,
    "refined-idea": AdapterCategory.CONDUCT,
    "implementing": AdapterCategory.CONDUCT,
    "reviewing-implementation": AdapterCategory.CONDUCT,
    "reviewed-implementation": AdapterCategory.POLISH,
    "polishing-implementation": AdapterCategory.POLISH,
    "implemented": AdapterCategory.USHER,
    "cancelled": AdapterCategory.SKIP,
    "blocked": AdapterCategory.WAIT,
    "stopped": AdapterCategory.SKIP,
    "failed": AdapterCategory.WAIT,
}

_EPIC_ADAPTER_MAP: Dict[str, AdapterCategory] = {
    "idea": AdapterCategory.REFINE,
    "refining-idea": AdapterCategory.REFINE,
    "refined-idea": AdapterCategory.SHEPHERD,
    "planning": AdapterCategory.SHEPHERD,
    "plan-drafted": AdapterCategory.REFINE,
    "refining-plan": AdapterCategory.REFINE,
    "planned": AdapterCategory.CONDUCT,
    "implementing": AdapterCategory.CONDUCT,
    "reviewing-implementation": AdapterCategory.CONDUCT,
    "reviewed-implementation": AdapterCategory.POLISH,
    "polishing-implementation": AdapterCategory.POLISH,
    "implemented": AdapterCategory.USHER,
    "release": AdapterCategory.USHER,
}


def classify_next_action(status: str, item_type: str = "epic") -> AdapterCategory:
    """Map a canonical item status to its downstream adapter category."""
    if not is_valid_item_status(status):
        raise ValueError(f"Unknown status: {status!r}")

    if item_type == "epic":
        epic_cat = _EPIC_ADAPTER_MAP.get(status)
        if epic_cat is not None:
            return epic_cat

    if item_type == "issue" and status == "idea":
        return AdapterCategory.REFINE

    cat = _STATUS_ADAPTER_MAP.get(status)
    if cat is None:
        raise ValueError(f"No adapter mapping for status: {status!r}")
    return cat
