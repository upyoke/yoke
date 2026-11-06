# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from dataclasses import replace

from yoke_contracts.timestamps import parse_instant

from runtime.api.domain.merge_queue_observer_test_helpers import observer_connection

from yoke_core.domain.merge_queue_enqueue_verification import LandingReadback

from yoke_core.domain.merge_queue_landing_record import (
    LandingRecord,
    from_readback,
    read_landing_record,
    write_landing_record,
)

from yoke_core.domain.merge_queue_landing_record_state import (
    CLOSED_UNMERGED,
    CONFLICTED,
    LANDED,
    PENDING,
    STALLED,
)

from yoke_core.domain.merge_queue_readiness import (
    ARMED_NOT_ENQUEUED,
    ENQUEUED,
    ENTRY_ABSENT,
    MERGE_WHEN_READY_ARMED,
    MERGE_WHEN_READY_CONSUMED,
)

from yoke_core.domain.merge_github_membership import PrQueueMembership

from yoke_core.domain.merge_github_queue import PrLandingState


def _record(state: str, observed_at: str, *, narrative: str) -> LandingRecord:
    return LandingRecord(
        item_id=101,
        project_id=1,
        pr_number="42",
        state=state,
        queue_holding=ENQUEUED,
        queue_entry_state="AWAITING_CHECKS",
        merge_when_ready=MERGE_WHEN_READY_CONSUMED,
        narrative=narrative,
        observed_at=observed_at,
        changed_at=observed_at,
    )
