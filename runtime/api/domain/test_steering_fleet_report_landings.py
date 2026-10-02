"""Fleet rows expose the same named landing-readiness facts."""

from __future__ import annotations

import pytest

from runtime.api.steering_fleet_test_helpers import (
    WORKER_SESSION,
    compose,
    seed_steering_scope,
)
from yoke_core.domain import merge_queue_read_reuse as reads_mod
from yoke_core.domain.steering_fleet_report_projection import report_dict
from yoke_core.domain.steering_fleet_report_render import report_body
from yoke_core.domain.sessions_lifecycle_claim import claim_work
from yoke_core.domain.work_claim_targets import make_item_target
from yoke_core.engines.merge_worktree_pr_check_runs import (
    LandingCheck,
    PrLandingProjection,
)
from yoke_core.engines.merge_worktree_pr_queue import PrLandingState, QueueMember


@pytest.fixture
def fleet(test_db):
    conn = seed_steering_scope(test_db)
    conn.execute(
        "UPDATE items SET status='implementing', merge_queue_pr_number='42', "
        "merge_queue_enqueued_at='2026-09-03T23:00:00Z' WHERE id=1"
    )
    conn.commit()
    return conn


def _wire(monkeypatch, *, state: PrLandingState, members, checks=()) -> None:
    monkeypatch.setattr(
        reads_mod,
        "read_pr_landing_and_required_checks",
        lambda _ctx, _pr: PrLandingProjection(state=state, required_checks=checks),
    )
    monkeypatch.setattr(
        reads_mod,
        "read_queue_members",
        lambda _ctx, base_branch="main": (list(members), None),
    )


def test_fleet_names_the_entry_state_when_arming_was_consumed(
    fleet, monkeypatch
) -> None:
    _wire(
        monkeypatch,
        state=PrLandingState(False, False, False, merge_state_status="blocked"),
        members=(QueueMember("42", "YOK-1", state="AWAITING_CHECKS"),),
    )

    report = compose(fleet)

    row = report.landings[0]
    assert row.readiness.in_flight is True
    assert row.readiness.queue_entry_state == "AWAITING_CHECKS"
    assert row.readiness.merge_when_ready == "consumed"
    assert report.landings_needing_action() == ()
    assert "queue-entry=AWAITING_CHECKS" in report_body(report)
    assert report_dict(report)["landings"][0]["queue_holding"] == "enqueued"


def test_fleet_marks_a_real_unarmed_landing_for_action(fleet, monkeypatch) -> None:
    _wire(
        monkeypatch,
        state=PrLandingState(False, False, False, merge_state_status="clean"),
        members=(),
    )

    report = compose(fleet)

    row = report.landings_needing_action()[0]
    assert row.readiness.queue_holding == "neither"
    assert row.readiness.queue_entry_state == "absent"
    assert row.readiness.merge_when_ready == "cleared"
    assert "! YOK-1" in report_body(report)
    assert report_dict(report)["landings_needing_action"][0]["item_id"] == 1


def test_an_open_verification_pr_is_not_yet_a_fleet_landing(fleet, monkeypatch) -> None:
    fleet.execute("UPDATE items SET merge_queue_enqueued_at=NULL WHERE id=1")
    fleet.commit()
    monkeypatch.setattr(
        reads_mod,
        "read_pr_landing_and_required_checks",
        lambda *_args, **_kwargs: pytest.fail("landing read should not run"),
    )

    assert compose(fleet).landings == ()


@pytest.mark.parametrize("queued", [False, True])
def test_idle_holder_waiting_on_healthy_landing_is_not_idle(fleet, monkeypatch, queued):
    claim_work(fleet, session_id=WORKER_SESSION, target=make_item_target(1))
    _wire(
        monkeypatch,
        state=PrLandingState(False, False, not queued),
        members=(QueueMember("42", "candidate", state="AWAITING_CHECKS"),)
        if queued
        else (),
    )

    report = compose(fleet)

    assert report.holders[0].idle_seconds > report.idle_after_seconds
    assert report.idle == ()
    assert "idle holders" not in report_body(report)
    assert len(report.landings) == 1


@pytest.mark.parametrize("queued", [False, True])
def test_failed_required_check_retains_idle_holder(fleet, monkeypatch, queued):
    claim_work(fleet, session_id=WORKER_SESSION, target=make_item_target(1))
    _wire(
        monkeypatch,
        state=PrLandingState(False, False, True),
        members=(QueueMember("42", "candidate", state="AWAITING_CHECKS"),)
        if queued
        else (),
        checks=(LandingCheck("tests", "completed", "failure", required=True),),
    )

    assert len(compose(fleet).idle) == 1


def test_dead_landing_retains_idle_holder(fleet, monkeypatch):
    claim_work(fleet, session_id=WORKER_SESSION, target=make_item_target(1))
    _wire(monkeypatch, state=PrLandingState(False, False, False), members=())

    report = compose(fleet)

    assert len(report.idle) == 1
    assert report.landings_needing_action()


def test_merged_landing_waits_for_wake_then_retains_idle_holder(fleet, monkeypatch):
    claim_work(fleet, session_id=WORKER_SESSION, target=make_item_target(1))
    _wire(monkeypatch, state=PrLandingState(True, True, False), members=())
    fleet.execute(
        "UPDATE items SET merge_queue_landed_at=%s WHERE id=1",
        ("2026-08-26T11:00:00Z",),
    )
    fleet.commit()

    assert compose(fleet).idle == ()

    fleet.execute(
        "UPDATE items SET merge_queue_notified_at=%s WHERE id=1",
        ("2026-08-26T11:01:00Z",),
    )
    fleet.commit()

    assert len(compose(fleet).idle) == 1
