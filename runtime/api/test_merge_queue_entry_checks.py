"""Red entry-check landing: terminal immediately, pending still uses budget."""

from runtime.api.merge_queue_landing_test_helpers import land, wire_happy_path
from runtime.api.test_merge_queue_landing_verdict import _classify, _wire
from runtime.api.test_merge_queue_route import stalled_clock

from yoke_core.domain import merge_queue_entry_checks as checks_mod
from yoke_core.domain import merge_queue_landing_verdict as verdict_mod
from yoke_core.domain import merge_queue_route as route_mod
from yoke_core.domain.merge_queue_landing_verdict import LandingCheck
from yoke_core.engines.merge_worktree_pr_queue import PrLandingState, TrainRun

RED_ARMED = PrLandingState(
    merged=False,
    closed=False,
    auto_merge_active=True,
    head_sha="a" * 40,
)


def test_red_entry_checks_return_immediately_without_the_poll_budget(
    monkeypatch,
):
    wire_happy_path(monkeypatch, landing_states=[RED_ARMED] * 100)
    monkeypatch.setattr(
        verdict_mod,
        "read_landing_checks",
        lambda _ctx, sha: (
            ((LandingCheck("ci", "completed", "failure"),), None)
            if sha == "a" * 40
            else ((), None)
        ),
    )
    monkeypatch.setattr(
        route_mod,
        "disarm_merge_when_ready",
        lambda *_a, **_k: "merge-when-ready disarmed",
    )
    announced: list[str] = []
    outcome = land(
        monotonic=stalled_clock(),
        deadline_seconds=120.0,
        emit=announced.append,
    )
    assert not outcome.ok
    assert outcome.exit_code == 1
    assert "entry-checks-failed" in outcome.error
    assert "concluded-checks=ci=failure" in outcome.error
    assert "merge-when-ready disarmed" in outcome.error
    assert "did not merge within" not in outcome.error
    assert any("concluded-checks=ci=failure" in line for line in announced)


def test_in_flight_entry_checks_still_spend_the_poll_budget(monkeypatch):
    wire_happy_path(monkeypatch, landing_states=[RED_ARMED] * 100)
    monkeypatch.setattr(
        verdict_mod,
        "read_landing_checks",
        lambda _ctx, _sha: ((LandingCheck("ci", "in_progress"),), None),
    )
    outcome = land(
        monotonic=stalled_clock(),
        deadline_seconds=120.0,
        emit=lambda _line: None,
    )
    assert not outcome.ok
    assert outcome.exit_code == route_mod.RECOVERABLE_QUEUE_EXIT_CODE
    assert "did not merge within" in outcome.error
    assert "pending-checks=ci" in outcome.error


def test_completed_success_is_not_red_entry_checks():
    checks = (LandingCheck("ci", "completed", "success"),)
    assert not checks_mod.entry_checks_are_red(checks)


def test_unreadable_or_empty_checks_are_not_red_entry_checks():
    assert not checks_mod.entry_checks_are_red(None)
    assert not checks_mod.entry_checks_are_red(())


def test_red_entry_checks_are_terminal_when_nothing_is_in_flight(monkeypatch):
    _wire(monkeypatch, states=[RED_ARMED])
    monkeypatch.setattr(
        verdict_mod,
        "read_landing_checks",
        lambda _ctx, sha: (
            ((LandingCheck("ci", "completed", "failure"),), None)
            if sha == "a" * 40
            else ((), None)
        ),
    )
    verdict = _classify()
    assert verdict.kind == verdict_mod.ENTRY_CHECKS_FAILED
    assert "concluded-checks=ci=failure" in verdict.narrative
    assert verdict.head_sha == "a" * 40


def test_in_flight_entry_checks_keep_the_poll_budget(monkeypatch):
    _wire(monkeypatch, states=[RED_ARMED])
    monkeypatch.setattr(
        verdict_mod,
        "read_landing_checks",
        lambda _ctx, _sha: ((LandingCheck("ci", "in_progress"),), None),
    )
    verdict = _classify()
    assert verdict.kind == verdict_mod.PENDING
    assert "pending-checks=ci" in verdict.narrative


def test_unarmed_red_entry_checks_are_terminal_after_confirm(monkeypatch):
    unarmed = PrLandingState(
        merged=False, closed=False, auto_merge_active=False, head_sha="a" * 40
    )
    _wire(monkeypatch, states=[unarmed, unarmed])
    monkeypatch.setattr(
        verdict_mod,
        "read_landing_checks",
        lambda _ctx, sha: (
            ((LandingCheck("ci", "completed", "failure"),), None)
            if sha == "a" * 40
            else ((), None)
        ),
    )
    verdict = _classify()
    assert verdict.kind == verdict_mod.ENTRY_CHECKS_FAILED
    assert verdict.head_sha == "a" * 40


def test_red_train_checks_are_not_entry_checks(monkeypatch):
    _wire(
        monkeypatch,
        states=[RED_ARMED],
        train=TrainRun(status="in_progress", head_sha="b" * 40),
    )
    monkeypatch.setattr(
        verdict_mod,
        "read_landing_checks",
        lambda _ctx, sha: (
            ((LandingCheck("ci", "completed", "failure"),), None)
            if sha == "b" * 40
            else ((), None)
        ),
    )
    assert _classify().kind == verdict_mod.PENDING
