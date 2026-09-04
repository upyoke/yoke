"""The waiter-triggered server observation is shared across one project."""

from runtime.api.domain.merge_queue_observer_test_helpers import (
    armed_awaiting_checks,
    checks_running,
    not_queued,
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
from yoke_core.domain.merge_queue_landing_record_state import PENDING
from yoke_core.domain.merge_queue_readiness import (
    ARMED_NOT_ENQUEUED,
    ENTRY_ABSENT,
    MERGE_WHEN_READY_ARMED,
)


def _request(item_id: int) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="merge_queue.landing.observe",
        actor=ActorContext(actor_id=None, session_id="s-waiter"),
        target=TargetRef(kind="item", item_id=item_id),
        payload={},
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

    def observe(db, project_ids, *, now):
        return observe_pending_landings(
            db,
            project_ids,
            now=now,
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

    def leave_refresh_in_progress(db, project_ids, *, now):
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

    def finish_without_this_candidate(db, project_ids, *, now):
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
