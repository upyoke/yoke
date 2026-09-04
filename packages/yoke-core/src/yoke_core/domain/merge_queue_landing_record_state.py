"""State vocabulary shared by durable landing records and their consumers."""

from yoke_core.domain.merge_queue_entry_checks import ENTRY_CHECKS_FAILED
from yoke_core.domain.merge_queue_readback_outcomes import (
    CLOSED_UNMERGED,
    CONFLICTED,
    LANDED,
)


PENDING = "pending"
STALLED = "stalled"

LANDING_RECORD_STATES = (
    PENDING,
    LANDED,
    CLOSED_UNMERGED,
    CONFLICTED,
    STALLED,
    ENTRY_CHECKS_FAILED,
)


__all__ = [
    "CLOSED_UNMERGED",
    "CONFLICTED",
    "ENTRY_CHECKS_FAILED",
    "LANDED",
    "LANDING_RECORD_STATES",
    "PENDING",
    "STALLED",
]
