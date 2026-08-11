"""Classifying one observation of a queued pull request."""

from yoke_core.domain import merge_queue_landing_verdict as verdict_mod
from yoke_core.engines.merge_worktree_pr_queue import (
    PrLandingState,
    QueueMember,
    TrainRun,
)
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext


ARMED = PrLandingState(merged=False, closed=False, auto_merge_active=True)
UNARMED = PrLandingState(merged=False, closed=False, auto_merge_active=False)
MERGED = PrLandingState(merged=True, closed=True, auto_merge_active=False)
CLOSED = PrLandingState(merged=False, closed=True, auto_merge_active=False)


def _ctx() -> MergeContext:
    return MergeContext(args=MergeArgs(branch="YOK-200"), project="yoke")


def _wire(monkeypatch, *, states, entries=(), train=None, train_note=None):
    reads: list[str] = []
    script = list(states)

    def read_state(_ctx, pr_num):
        reads.append(pr_num)
        return (script.pop(0) if script else states[-1]), None

    monkeypatch.setattr(verdict_mod, "read_pr_landing_state", read_state)
    monkeypatch.setattr(
        verdict_mod, "read_queue_members",
        lambda _ctx, base_branch="main": (list(entries), None),
    )
    monkeypatch.setattr(
        verdict_mod, "read_train_run", lambda _ctx, pr_num: (train, train_note)
    )
    return reads


def _classify(**overrides):
    kwargs = {"pr_num": "42", "target": "main", "sleep": lambda _s: None}
    kwargs.update(overrides)
    return verdict_mod.classify_landing(_ctx(), **kwargs)


def test_merged_is_landed_on_the_first_read(monkeypatch):
    reads = _wire(monkeypatch, states=[MERGED])
    assert _classify().kind == verdict_mod.LANDED
    assert len(reads) == 1


def test_armed_and_unmerged_is_pending_without_confirming(monkeypatch):
    reads = _wire(monkeypatch, states=[ARMED])
    assert _classify().kind == verdict_mod.PENDING
    assert len(reads) == 1


def test_cleared_arming_is_confirmed_before_any_verdict(monkeypatch):
    reads = _wire(monkeypatch, states=[UNARMED, MERGED])
    assert _classify().kind == verdict_mod.LANDED
    assert len(reads) == 2


def test_confirm_delay_precedes_the_second_read(monkeypatch):
    slept: list[float] = []
    _wire(monkeypatch, states=[UNARMED, MERGED])
    _classify(sleep=slept.append, confirm_seconds=7.5)
    assert slept == [7.5]


def test_still_queued_after_confirmation_is_pending(monkeypatch):
    _wire(
        monkeypatch,
        states=[UNARMED, UNARMED],
        entries=(QueueMember(pr_num="42", head_ref="YOK-200",
                             state="AWAITING_CHECKS"),),
    )
    assert _classify().kind == verdict_mod.PENDING


def test_rearmed_during_confirmation_is_pending(monkeypatch):
    _wire(monkeypatch, states=[UNARMED, ARMED])
    assert _classify().kind == verdict_mod.PENDING


def test_absent_from_the_queue_after_confirmation_is_stalled(monkeypatch):
    _wire(
        monkeypatch,
        states=[UNARMED, UNARMED],
        train=TrainRun(
            status="completed", conclusion="success", url="https://runs/3",
            matched_by_marker=True,
        ),
    )
    verdict = _classify()
    assert verdict.kind == verdict_mod.STALLED
    assert "queue-entry=absent" in verdict.narrative
    # A green train run behind a stalled pull request is reported as what it
    # is, not translated into a claim that the checks failed.
    assert "train-run=success (https://runs/3)" in verdict.narrative


def test_unreadable_queue_cannot_prove_absence(monkeypatch):
    _wire(monkeypatch, states=[UNARMED, UNARMED])
    monkeypatch.setattr(
        verdict_mod, "read_queue_members",
        lambda _ctx, base_branch="main": (None, "graphql refused"),
    )
    verdict = _classify()
    assert verdict.kind == verdict_mod.PENDING
    assert "graphql refused" in verdict.warnings


def test_closed_is_terminal_even_while_the_queue_is_unreadable(monkeypatch):
    _wire(monkeypatch, states=[CLOSED, CLOSED])
    monkeypatch.setattr(
        verdict_mod, "read_queue_members",
        lambda _ctx, base_branch="main": (None, "graphql refused"),
    )
    verdict = _classify()
    assert verdict.kind == verdict_mod.CLOSED_UNMERGED
    assert "queue-entry=unreadable" in verdict.narrative


def test_closed_that_turns_out_merged_is_landed(monkeypatch):
    _wire(monkeypatch, states=[CLOSED, MERGED])
    assert _classify().kind == verdict_mod.LANDED


def test_missing_train_run_is_named_rather_than_asserted(monkeypatch):
    _wire(
        monkeypatch, states=[UNARMED, UNARMED],
        train=None, train_note="no merge_group workflow run found",
    )
    verdict = _classify()
    assert "train-run=not found" in verdict.narrative
    assert "no merge_group workflow run found" in verdict.warnings


def test_unreadable_pull_request_is_pending(monkeypatch):
    monkeypatch.setattr(
        verdict_mod, "read_pr_landing_state",
        lambda _ctx, pr_num: (None, "github pr read failure"),
    )
    verdict = _classify()
    assert verdict.kind == verdict_mod.PENDING
    assert "github pr read failure" in verdict.warnings
