"""The waiter-triggered server observation is shared across one project."""

from datetime import timedelta

import pytest

from runtime.api.domain.merge_queue_observer_test_helpers import (
    armed_awaiting_checks,
    checks_running,
    merged,
    not_queued,
    observe as relay_sweep,
    observer_connection,
)
from runtime.api.domain.test_session_message_support import NOW
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import merge_queue_landing_observe as handler
from yoke_core.domain.merge_queue_landing_observer import observe_pending_landings
from yoke_core.domain.merge_queue_landing_record_state import LANDED, PENDING
from yoke_core.domain.merge_queue_landing_refresh import (
    LANDING_RECORD_STALE_SECONDS,
    REFRESH_CADENCE_SECONDS,
)
from yoke_core.domain.merge_queue_readiness import (
    ARMED_NOT_ENQUEUED,
    ENTRY_ABSENT,
    MERGE_WHEN_READY_ARMED,
)


def _request(item_id: int, **payload: object) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="merge_queue.landing.observe",
        actor=ActorContext(actor_id=None, session_id="s-waiter"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload,
    )


def test_waiter_call_refreshes_every_pending_landing_once_per_cadence(
    monkeypatch,
):
    conn = observer_connection()
    conn.execute(
        "INSERT INTO items "
        "(id,project_id,project_sequence,status,merge_queue_pr_number,"
        "merge_queue_enqueued_at) VALUES (102,1,2,'reviewing-implementation',"
        "'43','2026-08-27T17:00:00Z')"
    )
    conn.commit()
    reads: list[str] = []

    def read_state(ctx, pr_number):
        reads.append(str(pr_number))
        return armed_awaiting_checks(ctx, pr_number)

    def observe(db, project_ids, *, now, **kwargs):
        return observe_pending_landings(
            db,
            project_ids,
            now=now,
            **kwargs,
            read_state=read_state,
            read_membership=not_queued,
            read_checks=checks_running,
        )

    monkeypatch.setattr(handler, "_connect_rw", lambda: conn)
    monkeypatch.setattr(handler, "utc_now", lambda: NOW)
    monkeypatch.setattr(handler, "observe_pending_landings", observe)

    first = handler.handle_observe_landing(_request(101))
    second = handler.handle_observe_landing(_request(102))

    assert first.primary_success and second.primary_success
    handler.ObserveLandingResponse(**first.result_payload)
    handler.ObserveLandingResponse(**second.result_payload)
    assert first.result_payload["refreshed"] is True
    assert second.result_payload["refreshed"] is False
    assert first.result_payload["record"]["state"] == PENDING
    assert first.result_payload["record"]["queue_holding"] == ARMED_NOT_ENQUEUED
    assert first.result_payload["record"]["queue_entry_state"] == ENTRY_ABSENT
    assert first.result_payload["record"]["merge_when_ready"] == MERGE_WHEN_READY_ARMED
    assert second.result_payload["record"]["pr_number"] == "43"
    assert reads == ["42", "43"]


def test_recent_in_progress_refresh_is_waitable_before_first_record(monkeypatch):
    conn = observer_connection()

    def leave_refresh_in_progress(db, project_ids, *, now, **_kwargs):
        db.execute(
            "INSERT INTO merge_queue_landing_refreshes "
            "(project_id,started_at,completed_at,last_error) "
            "VALUES (1,'2026-08-22T16:00:00Z',NULL,'')"
        )
        db.commit()
        return {"checked": 0}

    monkeypatch.setattr(handler, "_connect_rw", lambda: conn)
    monkeypatch.setattr(handler, "utc_now", lambda: NOW)
    monkeypatch.setattr(handler, "observe_pending_landings", leave_refresh_in_progress)

    outcome = handler.handle_observe_landing(_request(101))

    assert outcome.primary_success
    assert outcome.result_payload["record"] is None
    assert outcome.result_payload["stale"] is False


def test_candidate_created_after_a_recent_sweep_waits_for_the_next_cadence(
    monkeypatch,
):
    conn = observer_connection()

    def finish_without_this_candidate(db, project_ids, *, now, **_kwargs):
        db.execute(
            "INSERT INTO merge_queue_landing_refreshes "
            "(project_id,started_at,completed_at,last_error) VALUES "
            "(1,'2026-08-22T16:00:00Z','2026-08-22T16:00:00Z','')"
        )
        db.commit()
        return {"checked": 0}

    monkeypatch.setattr(handler, "_connect_rw", lambda: conn)
    monkeypatch.setattr(handler, "utc_now", lambda: NOW)
    monkeypatch.setattr(
        handler,
        "observe_pending_landings",
        finish_without_this_candidate,
    )

    outcome = handler.handle_observe_landing(_request(101))

    assert outcome.primary_success
    assert outcome.result_payload["record"] is None
    assert outcome.result_payload["stale"] is False


def test_item_lookup_uses_the_name_aware_database_row(monkeypatch):
    conn = observer_connection()
    converted: list[object] = []

    def convert(row):
        converted.append(row)
        return {
            "project_id": row["project_id"],
            "merge_queue_pr_number": row["merge_queue_pr_number"],
        }

    monkeypatch.setattr(handler, "_connect_rw", lambda: conn)
    monkeypatch.setattr(handler, "row_dict", convert)
    monkeypatch.setattr(
        handler,
        "observe_pending_landings",
        lambda *_args, **_kwargs: {"checked": 0},
    )

    outcome = handler.handle_observe_landing(_request(101))

    assert outcome.primary_success
    assert len(converted) == 1


def _observe_with(monkeypatch, conn, *, now, read_state, reads):
    """Point the handler at `conn` at `now`, counting every GitHub state read."""

    def counted(ctx, pr_number):
        reads.append(str(pr_number))
        return read_state(ctx, pr_number)

    def observe(db, project_ids, *, now, **kwargs):
        return observe_pending_landings(
            db,
            project_ids,
            now=now,
            **kwargs,
            read_state=counted,
            read_membership=not_queued,
            read_checks=checks_running,
        )

    monkeypatch.setattr(handler, "_connect_rw", lambda: conn)
    monkeypatch.setattr(handler, "utc_now", lambda: now)
    monkeypatch.setattr(handler, "observe_pending_landings", observe)


def test_fresh_record_answers_without_reading_github(monkeypatch):
    conn = observer_connection()
    swept_at = NOW - timedelta(seconds=REFRESH_CADENCE_SECONDS)
    relay_sweep(
        conn,
        now=swept_at,
        read_state=armed_awaiting_checks,
        read_membership=not_queued,
    )
    reads: list[str] = []
    _observe_with(monkeypatch, conn, now=NOW, read_state=merged, reads=reads)

    outcome = handler.handle_observe_landing(_request(101))

    assert outcome.primary_success
    assert reads == []
    assert outcome.result_payload["refreshed"] is False
    assert outcome.result_payload["stale"] is False
    assert outcome.result_payload["record"]["state"] == PENDING
    assert outcome.result_payload["age_seconds"] == REFRESH_CADENCE_SECONDS


def test_stale_record_without_relay_refreshes_inline_and_reports_landing(
    monkeypatch,
):
    conn = observer_connection()
    swept_at = NOW - timedelta(seconds=LANDING_RECORD_STALE_SECONDS + 1)
    relay_sweep(
        conn,
        now=swept_at,
        read_state=armed_awaiting_checks,
        read_membership=not_queued,
    )
    reads: list[str] = []
    _observe_with(monkeypatch, conn, now=NOW, read_state=merged, reads=reads)

    outcome = handler.handle_observe_landing(_request(101))

    assert outcome.primary_success
    assert reads == ["42"]
    assert outcome.result_payload["refreshed"] is True
    assert outcome.result_payload["stale"] is False
    assert outcome.result_payload["record"]["state"] == LANDED


@pytest.mark.parametrize(
    ("swept_state", "expected_reads"), [(armed_awaiting_checks, ["42"]), (merged, [])]
)
def test_close_out_refreshes_a_fresh_record_unless_it_is_landed(
    monkeypatch, swept_state, expected_reads
):
    conn = observer_connection()
    # The sweep wrote its record seconds before GitHub merged the PR.
    relay_sweep(
        conn,
        now=NOW - timedelta(seconds=2),
        read_state=swept_state,
        read_membership=not_queued,
    )
    reads: list[str] = []
    _observe_with(monkeypatch, conn, now=NOW, read_state=merged, reads=reads)

    outcome = handler.handle_observe_landing(
        _request(101, refresh_unless_landed=True)
    )

    assert outcome.primary_success
    assert reads == expected_reads
    assert outcome.result_payload["record"]["state"] == LANDED


@pytest.mark.parametrize("relay_running", [True, False])
def test_merged_pull_request_is_reported_within_two_refresh_intervals(
    monkeypatch, relay_running
):
    conn = observer_connection()
    relay_sweep(
        conn,
        now=NOW,
        read_state=armed_awaiting_checks,
        read_membership=not_queued,
    )
    # The pull request merges right after that sweep; the waiter polls
    # every 15 seconds and the relay, when running, sweeps on cadence.
    poll_seconds = 15.0
    reported_after = None
    for step in range(1, 25):
        elapsed = step * poll_seconds
        moment = NOW + timedelta(seconds=elapsed)
        if relay_running and elapsed % REFRESH_CADENCE_SECONDS == 0:
            relay_sweep(
                conn,
                now=moment,
                read_state=merged,
                read_membership=not_queued,
                cadence_seconds=REFRESH_CADENCE_SECONDS,
            )
        _observe_with(monkeypatch, conn, now=moment, read_state=merged, reads=[])
        outcome = handler.handle_observe_landing(_request(101))
        assert outcome.result_payload["stale"] is False
        if outcome.result_payload["record"]["state"] == LANDED:
            reported_after = elapsed
            break

    assert reported_after is not None
    assert reported_after <= LANDING_RECORD_STALE_SECONDS + poll_seconds


def test_unarmed_attempt_still_returns_the_completed_landing(monkeypatch):
    from yoke_core.domain.merge_queue_landing_marker import point_item_at_pull_request

    conn = observer_connection()
    relay_sweep(conn, now=NOW, read_state=merged, read_membership=not_queued)
    conn.execute(
        "UPDATE items SET merge_queue_notified_at='2026-08-22T16:00:00Z' WHERE id=101"
    )
    conn.commit()
    point_item_at_pull_request(conn, 101, "43")
    reads = []
    _observe_with(monkeypatch, conn, now=NOW, read_state=merged, reads=reads)

    outcome = handler.handle_observe_landing(_request(101))

    assert outcome.primary_success
    assert outcome.result_payload["record"]["pr_number"] == "42"
    assert outcome.result_payload["record"]["state"] == LANDED
    assert reads == []
