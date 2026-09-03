"""Red required checks are terminal; a set still running keeps the budget."""

from runtime.api.merge_queue_landing_test_helpers import land, wire_happy_path
from runtime.api.test_merge_queue_landing_verdict import _classify, _wire
from runtime.api.test_merge_queue_route import stalled_clock

from yoke_core.domain import merge_queue_entry_checks as checks_mod
from yoke_core.domain import merge_queue_landing_verdict as verdict_mod
from yoke_core.domain import merge_queue_landing_wait as wait_mod
from yoke_core.domain import merge_queue_route as route_mod
from yoke_core.engines.merge_worktree_pr_check_runs import LandingCheck
from yoke_core.engines.merge_worktree_pr_queue import PrLandingState, TrainRun

RED_ARMED = PrLandingState(
    merged=False,
    closed=False,
    auto_merge_active=True,
    merge_state_status="blocked",
    head_sha="a" * 40,
)

RUN_URL = "https://github.com/o/r/actions/runs/1/job/2"

FAILED_REQUIRED = LandingCheck(
    name="repo-contracts",
    status="completed",
    conclusion="failure",
    required=True,
    url=RUN_URL,
)
PENDING_REQUIRED = LandingCheck(name="test-shard", status="in_progress", required=True)
FAILED_OPTIONAL = LandingCheck(
    name="reuse-coverage", status="completed", conclusion="failure"
)


def _required(monkeypatch, module, *checks):
    monkeypatch.setattr(
        module, "read_required_checks", lambda _ctx, _pr: (tuple(checks), None)
    )


def test_a_red_required_check_ends_the_wait_without_the_poll_budget(monkeypatch):
    """The named case: BLOCKED plus one red required check is not a wait."""
    wire_happy_path(monkeypatch, landing_states=[RED_ARMED] * 100)
    _required(monkeypatch, verdict_mod, FAILED_REQUIRED, PENDING_REQUIRED)
    monkeypatch.setattr(
        wait_mod,
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
    # The check and the run that explains it, so the holder does not have
    # to read `gh pr checks` by hand to find out what went red.
    assert "repo-contracts=failure" in outcome.error
    assert RUN_URL in outcome.error
    assert "re-run the verification gate" in outcome.error
    assert "merge-when-ready disarmed" in outcome.error
    assert "did not merge within" not in outcome.error
    assert any("concluded-checks=repo-contracts=failure" in x for x in announced)


def test_checks_still_running_spend_the_poll_budget(monkeypatch):
    """BLOCKED with everything pending is the ordinary armed-and-waiting."""
    wire_happy_path(monkeypatch, landing_states=[RED_ARMED] * 100)
    _required(monkeypatch, verdict_mod, PENDING_REQUIRED)
    outcome = land(
        monotonic=stalled_clock(),
        deadline_seconds=120.0,
        emit=lambda _line: None,
    )
    assert not outcome.ok
    assert outcome.exit_code == route_mod.RECOVERABLE_QUEUE_EXIT_CODE
    assert "did not merge within" in outcome.error
    assert "pending-checks=test-shard" in outcome.error


def test_a_failed_optional_check_does_not_refuse_the_entry():
    """Only the checks GitHub gates the entry on can make it impossible."""
    assert checks_mod.failed_required_checks((FAILED_OPTIONAL,)) == ()


def test_a_successful_required_check_is_not_red():
    green = LandingCheck("ci", "completed", "success", required=True)
    assert checks_mod.failed_required_checks((green,)) == ()


def test_unreadable_or_empty_checks_are_not_red():
    assert checks_mod.failed_required_checks(None) == ()
    assert checks_mod.failed_required_checks(()) == ()


def test_a_red_required_check_is_terminal_on_one_read(monkeypatch):
    _wire(monkeypatch, states=[RED_ARMED])
    _required(monkeypatch, verdict_mod, FAILED_REQUIRED, PENDING_REQUIRED)
    verdict = _classify()
    assert verdict.kind == verdict_mod.ENTRY_CHECKS_FAILED
    assert "concluded-checks=repo-contracts=failure" in verdict.narrative
    assert verdict.head_sha == "a" * 40
    assert verdict.failed_checks == (FAILED_REQUIRED,)


def test_checks_still_running_keep_the_poll_budget(monkeypatch):
    _wire(monkeypatch, states=[RED_ARMED])
    _required(monkeypatch, verdict_mod, PENDING_REQUIRED)
    verdict = _classify()
    assert verdict.kind == verdict_mod.PENDING
    assert "pending-checks=test-shard" in verdict.narrative


def test_an_unreadable_rollup_keeps_the_poll_budget(monkeypatch):
    """An unreadable rollup proves nothing, so it cannot end the wait."""
    _wire(monkeypatch, states=[RED_ARMED])
    monkeypatch.setattr(
        verdict_mod,
        "read_required_checks",
        lambda _ctx, _pr: (None, "required-checks read failed: transport"),
    )
    verdict = _classify()
    assert verdict.kind == verdict_mod.PENDING
    assert "required-checks read failed" in verdict.warnings[0]


def test_unarmed_red_required_checks_are_terminal_after_confirm(monkeypatch):
    unarmed = PrLandingState(
        merged=False, closed=False, auto_merge_active=False, head_sha="a" * 40
    )
    _wire(monkeypatch, states=[unarmed, unarmed])
    _required(monkeypatch, verdict_mod, FAILED_REQUIRED)
    verdict = _classify()
    assert verdict.kind == verdict_mod.ENTRY_CHECKS_FAILED
    assert verdict.head_sha == "a" * 40


def test_red_train_checks_are_not_entry_checks(monkeypatch):
    """Once a train builds, its commit's checks are not the entry gate."""
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
    _required(monkeypatch, verdict_mod, FAILED_REQUIRED)
    assert _classify().kind == verdict_mod.PENDING
