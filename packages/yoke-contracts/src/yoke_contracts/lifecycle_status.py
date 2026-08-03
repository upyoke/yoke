"""Lifecycle-status vocabulary — pure, client-tier.

The set of statuses that count as terminal success for a workflow task.
Hosted in yoke_contracts so the board render ships core-free;
``yoke_core.domain.task_lifecycle`` re-exports it for its callers.
"""

from __future__ import annotations

from typing import FrozenSet, Mapping


LEGACY_STATUS_GLYPHS: Mapping[str, str] = {
    "idea": "\U0001f4a1",
    "refining-idea": "📝",
    "refined-idea": "\U0001f48e",
    "planning": "📐",
    "plan-drafted": "📋",
    "refining-plan": "📝",
    "planned": "💎",
    "implementing": "\U0001f528",
    "reviewing-implementation": "\U0001f440",
    "reviewed-implementation": "👍",
    "polishing-implementation": "✨",
    "implemented": "⛳",
    "release": "\U0001f680",
    "done": "✅",
    "blocked": "⛔",
    "stopped": "\U0001f6d1",
    "cancelled": "🚫",
    "failed": "❗",
}
LEGACY_STATUS_BUCKETS: Mapping[str, str] = {
    "done": "done",
    "cancelled": "done",
    "blocked": "blocked",
    "stopped": "blocked",
    "failed": "blocked",
    "release": "release",
    "implemented": "implemented",
    "implementing": "implementing",
    "reviewing-implementation": "reviewing",
    "reviewed-implementation": "reviewing",
    "polishing-implementation": "reviewing",
    "refined-idea": "refined",
    "planned": "refined",
    "refining-idea": "planning",
    "planning": "planning",
    "plan-drafted": "planning",
    "refining-plan": "planning",
    "idea": "idea",
}
"""Renderer fallback for workflow versions published without stage glyphs."""

TASK_TERMINAL_SUCCESS: FrozenSet[str] = frozenset(
    {
        "done",
        "reviewed-implementation",
        "polishing-implementation",
        "implemented",
        "release",
    }
)


__all__ = [
    "LEGACY_STATUS_BUCKETS",
    "LEGACY_STATUS_GLYPHS",
    "TASK_TERMINAL_SUCCESS",
]
