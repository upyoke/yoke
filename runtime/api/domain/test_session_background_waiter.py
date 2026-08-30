"""Session-scoped background waiter arm, heartbeat, and completion contract."""

from __future__ import annotations

from datetime import datetime, timezone

from runtime.api.steering_fleet_test_helpers import seed_session
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.sessions_orchestration import handle_touch
from yoke_core.domain.session_background_waiter import (
    arm_background_waiter,
    complete_background_waiter,
    pulse_background_waiter,
    refresh_background_waiter_deadline,
)
from yoke_core.domain.sessions_lifecycle_registry import heartbeat


ARMED_AT = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)


def test_arm_records_fact_and_expected_heartbeat(test_db) -> None:
    seed_session(test_db, "waiter-session")
    test_db.commit()

    facts = arm_background_waiter(
        test_db,
        "waiter-session",
        waiter_id="wait-1",
        kind="qa_case",
        watched_fact="watch_qa_case completion",
        now=ARMED_AT,
    )

    assert facts == {
        "waiter_id": "wait-1",
        "kind": "qa_case",
        "watched_fact": "watch_qa_case completion",
        "armed_at": "2026-08-29T12:00:00Z",
        "expected_by": "2026-08-29T12:03:00Z",
        "completed_at": None,
        "active": True,
    }


def test_matching_waiter_pulse_extends_the_expected_by_deadline(test_db) -> None:
    seed_session(test_db, "waiter-session")
    test_db.commit()
    arm_background_waiter(
        test_db,
        "waiter-session",
        waiter_id="wait-1",
        kind="merge",
        watched_fact="watch_merge completion",
        now=ARMED_AT,
    )

    stale = refresh_background_waiter_deadline(
        test_db,
        "waiter-session",
        waiter_id="old-wait",
        now=datetime(2026, 8, 29, 12, 2, tzinfo=timezone.utc),
    )
    receipt = pulse_background_waiter(
        test_db,
        "waiter-session",
        waiter_id="wait-1",
        now=datetime(2026, 8, 29, 12, 2, tzinfo=timezone.utc),
    )
    row = test_db.execute(
        "SELECT background_waiter_expected_by FROM harness_sessions "
        "WHERE session_id = 'waiter-session'"
    ).fetchone()

    assert stale is False
    assert receipt["refreshed"] is True
    assert row[0] == "2026-08-29T12:05:00Z"


def test_ordinary_session_heartbeat_does_not_mask_a_dead_waiter(test_db) -> None:
    seed_session(test_db, "waiter-session")
    test_db.commit()
    arm_background_waiter(
        test_db,
        "waiter-session",
        waiter_id="wait-1",
        kind="merge",
        watched_fact="watch_merge completion",
        now=ARMED_AT,
    )

    heartbeat(test_db, "waiter-session")
    row = test_db.execute(
        "SELECT background_waiter_expected_by FROM harness_sessions "
        "WHERE session_id = 'waiter-session'"
    ).fetchone()

    assert row[0] == "2026-08-29T12:03:00Z"


def test_old_process_cannot_complete_a_replacement_waiter(test_db) -> None:
    seed_session(test_db, "waiter-session")
    test_db.commit()
    for token in ("old-wait", "new-wait"):
        arm_background_waiter(
            test_db,
            "waiter-session",
            waiter_id=token,
            kind="ci_run",
            watched_fact="watch_ci_run completion",
            now=ARMED_AT,
        )

    stale = complete_background_waiter(
        test_db, "waiter-session", waiter_id="old-wait", now=ARMED_AT
    )
    current = complete_background_waiter(
        test_db, "waiter-session", waiter_id="new-wait", now=ARMED_AT
    )

    assert stale["completed"] is False
    assert stale["waiter_id"] == "new-wait"
    assert current["completed"] is True
    assert current["active"] is False


def test_registered_touch_exposes_the_arm_receipt(test_db, monkeypatch) -> None:
    seed_session(test_db, "waiter-session")
    test_db.commit()
    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", lambda: test_db)
    request = FunctionCallRequest(
        function="sessions.touch",
        actor=ActorContext(actor_id="2", session_id="waiter-session"),
        target=TargetRef(kind="global"),
        payload={
            "background_waiter": {
                "action": "arm",
                "waiter_id": "wait-1",
                "kind": "qa_case",
                "watched_fact": "watch_qa_case completion",
            }
        },
    )

    outcome = handle_touch(request)

    assert outcome.primary_success
    assert outcome.result_payload["background_waiter"]["waiter_id"] == "wait-1"
    assert outcome.result_payload["background_waiter"]["active"] is True


def test_registered_touch_accepts_the_matching_waiter_pulse(
    test_db, monkeypatch
) -> None:
    seed_session(test_db, "waiter-session")
    test_db.commit()
    arm_background_waiter(
        test_db,
        "waiter-session",
        waiter_id="wait-1",
        kind="qa_case",
        watched_fact="watch_qa_case completion",
        now=ARMED_AT,
    )
    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", lambda: test_db)

    def pulse(waiter_id: str):
        return handle_touch(
            FunctionCallRequest(
                function="sessions.touch",
                actor=ActorContext(actor_id="2", session_id="waiter-session"),
                target=TargetRef(kind="global"),
                payload={
                    "background_waiter": {
                        "action": "pulse",
                        "waiter_id": waiter_id,
                    }
                },
            )
        )

    current = pulse("wait-1")

    assert current.primary_success
    assert current.result_payload["background_waiter"]["refreshed"] is True
