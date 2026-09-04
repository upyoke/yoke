"""Durable landing records preserve both freshness and semantic change time."""

from dataclasses import replace

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
from yoke_core.engines.merge_worktree_pr_membership import PrQueueMembership
from yoke_core.engines.merge_worktree_pr_queue import PrLandingState


def _record(state: str, observed_at: str, *, narrative: str) -> LandingRecord:
    return LandingRecord(
        item_id=101,
        project_id=1,
        pr_number="42",
        state=state,
        narrative=narrative,
        observed_at=observed_at,
        changed_at=observed_at,
    )


def test_repeated_facts_refresh_observed_at_without_faking_a_state_change():
    conn = observer_connection()
    write_landing_record(
        conn,
        _record(PENDING, "2026-08-22T16:00:00Z", narrative="still queued"),
    )
    write_landing_record(
        conn,
        _record(PENDING, "2026-08-22T16:01:00Z", narrative="still queued"),
    )
    conn.commit()

    record = read_landing_record(conn, 101)

    assert record is not None
    assert record.observed_at == "2026-08-22T16:01:00Z"
    assert record.changed_at == "2026-08-22T16:00:00Z"


def test_a_changed_fact_advances_the_state_change_time():
    conn = observer_connection()
    write_landing_record(
        conn,
        _record(PENDING, "2026-08-22T16:00:00Z", narrative="still queued"),
    )
    write_landing_record(
        conn,
        _record(
            CONFLICTED,
            "2026-08-22T16:01:00Z",
            narrative="mergeStateStatus=DIRTY",
        ),
    )
    conn.commit()

    record = read_landing_record(conn, 101)

    assert record is not None
    assert record.state == CONFLICTED
    assert record.changed_at == "2026-08-22T16:01:00Z"


def test_a_changed_queue_outcome_advances_the_state_change_time():
    conn = observer_connection()
    first = _record(PENDING, "2026-08-22T16:00:00Z", narrative="still held")
    write_landing_record(
        conn,
        replace(
            first,
            queue_holding=ARMED_NOT_ENQUEUED,
            queue_entry_state=ENTRY_ABSENT,
            merge_when_ready=MERGE_WHEN_READY_ARMED,
        ),
    )
    write_landing_record(
        conn,
        replace(
            first,
            queue_holding=ENQUEUED,
            queue_entry_state="AWAITING_CHECKS",
            merge_when_ready=MERGE_WHEN_READY_CONSUMED,
            observed_at="2026-08-22T16:01:00Z",
            changed_at="2026-08-22T16:01:00Z",
        ),
    )
    conn.commit()

    record = read_landing_record(conn, 101)

    assert record is not None
    assert record.queue_holding == ENQUEUED
    assert record.changed_at == "2026-08-22T16:01:00Z"


def test_queue_entry_outcomes_are_structured_with_readiness_names():
    record = from_readback(
        item_id=101,
        project_id=1,
        pr_number="42",
        readback=LandingReadback(
            state=PrLandingState(
                merged=False,
                closed=False,
                auto_merge_active=False,
            ),
            membership=PrQueueMembership(
                in_queue=True,
                entry_state="AWAITING_CHECKS",
                mergeable="MERGEABLE",
            ),
            required_checks=(),
        ),
        observed_at="2026-08-22T16:00:00Z",
    )

    assert record.queue_holding == ENQUEUED
    assert record.queue_entry_state == "AWAITING_CHECKS"
    assert record.merge_when_ready == MERGE_WHEN_READY_CONSUMED


def test_armed_without_an_entry_keeps_the_distinct_readiness_outcomes():
    record = from_readback(
        item_id=101,
        project_id=1,
        pr_number="42",
        readback=LandingReadback(
            state=PrLandingState(
                merged=False,
                closed=False,
                auto_merge_active=True,
            ),
            membership=PrQueueMembership(in_queue=False, mergeable="MERGEABLE"),
            required_checks=(),
        ),
        observed_at="2026-08-22T16:00:00Z",
    )

    assert record.queue_holding == ARMED_NOT_ENQUEUED
    assert record.queue_entry_state == ENTRY_ABSENT
    assert record.merge_when_ready == MERGE_WHEN_READY_ARMED


def test_closed_and_unheld_open_pull_requests_keep_distinct_recoveries():
    membership = PrQueueMembership(in_queue=False, mergeable="MERGEABLE")

    def classify(*, closed: bool):
        return from_readback(
            item_id=101,
            project_id=1,
            pr_number="42",
            readback=LandingReadback(
                state=PrLandingState(
                    merged=False,
                    closed=closed,
                    auto_merge_active=False,
                ),
                membership=membership,
                required_checks=(),
            ),
            observed_at="2026-08-22T16:00:00Z",
        )

    assert classify(closed=True).state == CLOSED_UNMERGED
    assert classify(closed=False).state == STALLED
