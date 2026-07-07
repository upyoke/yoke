"""Lifecycle-status vocabulary — pure, client-tier.

The set of statuses that count as terminal success for a workflow task.
Hosted in yoke_contracts so the board render ships core-free;
``yoke_core.domain.lifecycle_predicates`` re-exports it for its callers.
"""

from __future__ import annotations

from typing import FrozenSet

TASK_TERMINAL_SUCCESS: FrozenSet[str] = frozenset({
    "done", "reviewed-implementation", "polishing-implementation", "implemented",
    "release",
})
