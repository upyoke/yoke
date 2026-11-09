"""State vocabulary shared by durable landing records and their consumers."""

from yoke_core.domain.merge_queue_landing_record_schema import (
    CLOSED_UNMERGED, CONFLICTED, ENTRY_CHECKS_FAILED, LANDED,
    LANDING_RECORD_STATES, PENDING, STALLED,
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
