"""Canonical taxonomy for ``SchedulerOfferSkipped.skip_reason``.

Sibling helper to :mod:`yoke_core.domain.scheduler_events`. Owns the
authoritative set of valid ``skip_reason`` values for the
``SchedulerOfferSkipped`` event plus a lightweight validation helper.
Splitting this constant out of the events module keeps the events file
inside its per-file line cap and gives downstream consumers
(scheduler/frontier filters, doctor surfaces) a single import path for
the taxonomy.
"""

from __future__ import annotations

from typing import FrozenSet


SKIP_REASON_STALE_LIFECYCLE = "stale_lifecycle"
SKIP_REASON_STALE_LIFECYCLE_POST_CLAIM = "stale_lifecycle_post_claim"
SKIP_REASON_LIVE_CLAIM_CONFLICT = "live_claim_conflict"
SKIP_REASON_RECOVERABLE_SUBSTRATE = "recoverable_substrate"
SKIP_REASON_PROCESS_DISABLED_BY_CONFIG = "process_disabled_by_config"
SKIP_REASON_PATH_CLAIM_BLOCKED = "path_claim_blocked"


SKIP_REASONS: FrozenSet[str] = frozenset(
    {
        SKIP_REASON_STALE_LIFECYCLE,
        SKIP_REASON_STALE_LIFECYCLE_POST_CLAIM,
        SKIP_REASON_LIVE_CLAIM_CONFLICT,
        SKIP_REASON_RECOVERABLE_SUBSTRATE,
        SKIP_REASON_PROCESS_DISABLED_BY_CONFIG,
        SKIP_REASON_PATH_CLAIM_BLOCKED,
    }
)


def is_valid_skip_reason(reason: str) -> bool:
    """Return ``True`` when ``reason`` is in the canonical taxonomy."""
    return reason in SKIP_REASONS


__all__ = [
    "SKIP_REASONS",
    "SKIP_REASON_STALE_LIFECYCLE",
    "SKIP_REASON_STALE_LIFECYCLE_POST_CLAIM",
    "SKIP_REASON_LIVE_CLAIM_CONFLICT",
    "SKIP_REASON_RECOVERABLE_SUBSTRATE",
    "SKIP_REASON_PROCESS_DISABLED_BY_CONFIG",
    "SKIP_REASON_PATH_CLAIM_BLOCKED",
    "is_valid_skip_reason",
]
