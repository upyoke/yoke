"""Closed vocabulary for what kind of target a deployment flow deploys to.

``persistent`` names a registered environment row and requires an
environment; ``ephemeral`` deploys per-run preview substrate from unmerged
branches; ``None`` marks merge-only flows with no deploy target.
"""

from __future__ import annotations


TARGET_TIER_PERSISTENT = "persistent"
TARGET_TIER_EPHEMERAL = "ephemeral"
VALID_TARGET_TIERS = (TARGET_TIER_PERSISTENT, TARGET_TIER_EPHEMERAL)


__all__ = [
    "TARGET_TIER_EPHEMERAL",
    "TARGET_TIER_PERSISTENT",
    "VALID_TARGET_TIERS",
]
