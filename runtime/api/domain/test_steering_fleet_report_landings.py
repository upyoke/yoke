"""Fleet rows expose the same named landing-readiness facts."""

from __future__ import annotations

import pytest

from runtime.api.steering_fleet_test_helpers import compose, seed_steering_scope
from yoke_core.domain import merge_queue_readiness as readiness_mod
from yoke_core.domain.steering_fleet_report_projection import report_dict
from yoke_core.domain.steering_fleet_report_render import report_body
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


def _wire(monkeypatch, *, state: PrLandingState, members) -> None:
    monkeypatch.setattr(
        readiness_mod,
        "read_pr_landing_state",
        lambda _ctx, _pr: (state, None),
    )
    monkeypatch.setattr(
        readiness_mod,
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


def test_an_open_verification_pr_is_not_yet_a_fleet_landing(
    fleet, monkeypatch
) -> None:
    fleet.execute(
        "UPDATE items SET merge_queue_enqueued_at=NULL WHERE id=1"
    )
    fleet.commit()
    monkeypatch.setattr(
        readiness_mod,
        "read_pr_landing_state",
        lambda *_args, **_kwargs: pytest.fail("landing read should not run"),
    )

    assert compose(fleet).landings == ()
