"""Classifying one observation of a queued pull request."""

from yoke_core.domain import merge_queue_landing_verdict as verdict_mod
from yoke_core.domain.merge_queue_landing_verdict import LandingCheck
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
DIRTY = PrLandingState(
    merged=False,
    closed=False,
    auto_merge_active=True,
    merge_state_status="dirty",
)
CLEAN = PrLandingState(
    merged=False,
    closed=False,
    auto_merge_active=True,
    merge_state_status="clean",
)


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
        verdict_mod,
        "read_queue_members",
        lambda _ctx, base_branch="main": (list(entries), None),
    )
    monkeypatch.setattr(
        verdict_mod, "read_train_run", lambda _ctx, pr_num: (train, train_note)
    )
    monkeypatch.setattr(
        verdict_mod, "read_landing_checks", lambda _ctx, _sha: ((), None)
    )
    monkeypatch.setattr(
        verdict_mod, "read_required_checks", lambda _ctx, _pr: ((), None)
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


def test_a_pending_observation_names_what_it_is_waiting_on(monkeypatch):
    reads = _wire(
        monkeypatch,
        states=[ARMED],
        entries=(
            QueueMember(pr_num="42", head_ref="YOK-200", state="AWAITING_CHECKS"),
        ),
        train=TrainRun(status="in_progress", url="https://runs/9"),
    )
    verdict = _classify()
    assert verdict.kind == verdict_mod.PENDING
    assert "queue-entry=AWAITING_CHECKS" in verdict.narrative
    assert "train-run=in_progress (https://runs/9)" in verdict.narrative
    assert "mergeStateStatus=unreported" in verdict.narrative
    # Naming the wait costs the queue and train reads, not a second
    # pull-request read: the confirm delay stays a terminal-verdict cost.
    assert len(reads) == 1


def test_a_pull_request_the_queue_never_took_up_is_visible_while_pending(
    monkeypatch,
):
    """The doomed wait: armed and open, but nothing is driving it."""
    _wire(monkeypatch, states=[ARMED], entries=(), train=None)
    verdict = _classify()
    assert verdict.kind == verdict_mod.PENDING
    assert "queue-entry=absent" in verdict.narrative
    assert "train-run=not identified" in verdict.narrative


def test_a_merged_observation_reports_the_merge(monkeypatch):
    _wire(monkeypatch, states=[MERGED])
    assert "merged=true" in _classify().narrative


def test_an_unreadable_pull_request_says_so_rather_than_nothing(monkeypatch):
    monkeypatch.setattr(
        verdict_mod,
        "read_pr_landing_state",
        lambda _ctx, pr_num: (None, "github pr read failure"),
    )
    assert "unreadable" in _classify().narrative


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
        entries=(
            QueueMember(pr_num="42", head_ref="YOK-200", state="AWAITING_CHECKS"),
        ),
    )
    assert _classify().kind == verdict_mod.PENDING


def test_rearmed_during_confirmation_is_pending(monkeypatch):
    _wire(monkeypatch, states=[UNARMED, ARMED])
    assert _classify().kind == verdict_mod.PENDING


def test_absent_after_a_green_train_is_still_pending(monkeypatch):
    _wire(
        monkeypatch,
        states=[UNARMED, UNARMED],
        train=TrainRun(
            status="completed",
            conclusion="success",
            url="https://runs/3",
        ),
    )
    verdict = _classify()
    assert verdict.kind == verdict_mod.PENDING
    assert "queue-entry=absent" in verdict.narrative
    # A green train with the slot already cleared is the merge-in-flight
    # window, not a stall. Name the train; do not claim the checks failed.
    assert "train-run=success (https://runs/3)" in verdict.narrative


def test_absent_after_a_failed_train_is_stalled(monkeypatch):
    _wire(
        monkeypatch,
        states=[UNARMED, UNARMED],
        train=TrainRun(
            status="completed",
            conclusion="failure",
            url="https://runs/9",
        ),
    )
    verdict = _classify()
    assert verdict.kind == verdict_mod.STALLED
    assert "queue-entry=absent" in verdict.narrative
    assert "train-run=failure (https://runs/9)" in verdict.narrative


def test_absent_while_the_train_is_still_running_is_pending(monkeypatch):
    _wire(
        monkeypatch,
        states=[UNARMED, UNARMED],
        train=TrainRun(status="in_progress", url="https://runs/4"),
    )
    verdict = _classify()
    assert verdict.kind == verdict_mod.PENDING
    assert "train-run=in_progress (https://runs/4)" in verdict.narrative


def test_unreadable_queue_cannot_prove_absence(monkeypatch):
    _wire(monkeypatch, states=[UNARMED, UNARMED])
    monkeypatch.setattr(
        verdict_mod,
        "read_queue_members",
        lambda _ctx, base_branch="main": (None, "graphql refused"),
    )
    verdict = _classify()
    assert verdict.kind == verdict_mod.PENDING
    assert "graphql refused" in verdict.warnings


def test_closed_is_terminal_even_while_the_queue_is_unreadable(monkeypatch):
    _wire(monkeypatch, states=[CLOSED, CLOSED])
    monkeypatch.setattr(
        verdict_mod,
        "read_queue_members",
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
        monkeypatch,
        states=[UNARMED, UNARMED],
        train=None,
        train_note="no merge_group workflow run found",
    )
    verdict = _classify()
    # A pull request the queue has dropped before any train carried it
    # leaves no queue ref bearing its marker, so "not identified" is the
    # normal reading of an ejection rather than evidence of work in
    # flight. Treating it as still landing is what spent the whole poll
    # budget on a wait that had already ended.
    assert verdict.kind == verdict_mod.STALLED
    assert "train-run=not identified" in verdict.narrative
    assert "no merge_group workflow run found" in verdict.warnings


def test_unreadable_pull_request_is_pending(monkeypatch):
    monkeypatch.setattr(
        verdict_mod,
        "read_pr_landing_state",
        lambda _ctx, pr_num: (None, "github pr read failure"),
    )
    verdict = _classify()
    assert verdict.kind == verdict_mod.PENDING
    assert "github pr read failure" in verdict.warnings


def test_pending_observation_names_pending_and_concluded_checks(monkeypatch):
    _wire(
        monkeypatch,
        states=[ARMED],
        entries=(
            QueueMember(pr_num="42", head_ref="YOK-200", state="AWAITING_CHECKS"),
        ),
        train=TrainRun(status="in_progress", head_sha="abc123"),
    )
    monkeypatch.setattr(
        verdict_mod,
        "read_landing_checks",
        lambda _ctx, sha: (
            (
                (
                    LandingCheck("lint", "in_progress"),
                    LandingCheck("ci", "completed", "success"),
                ),
                None,
            )
            if sha == "abc123"
            else ((), None)
        ),
    )
    verdict = _classify()
    assert verdict.kind == verdict_mod.PENDING
    assert "pending-checks=lint" in verdict.narrative
    assert "concluded-checks=ci=success" in verdict.narrative


def test_unreadable_checks_warn_without_inventing_a_check_set(monkeypatch):
    _wire(
        monkeypatch,
        states=[ARMED],
        train=TrainRun(status="in_progress", head_sha="abc123"),
    )
    monkeypatch.setattr(
        verdict_mod,
        "read_landing_checks",
        lambda _ctx, _sha: (None, "check-runs read failed"),
    )
    verdict = _classify()
    assert "pending-checks=" not in verdict.narrative
    assert "check-runs read failed" in verdict.warnings


def test_a_pending_observation_names_merge_state_status(monkeypatch):
    _wire(monkeypatch, states=[CLEAN])
    verdict = _classify()
    assert verdict.kind == verdict_mod.PENDING
    assert "mergeStateStatus=CLEAN" in verdict.narrative


def test_dirty_while_armed_is_conflicted_after_confirm(monkeypatch):
    reads = _wire(monkeypatch, states=[DIRTY, DIRTY])
    verdict = _classify()
    assert verdict.kind == verdict_mod.CONFLICTED
    assert "mergeStateStatus=DIRTY" in verdict.narrative
    assert len(reads) == 2


def test_dirty_then_clean_during_confirm_stays_pending(monkeypatch):
    _wire(monkeypatch, states=[DIRTY, CLEAN])
    verdict = _classify()
    assert verdict.kind == verdict_mod.PENDING
    assert "mergeStateStatus=CLEAN" in verdict.narrative


def test_unknown_merge_state_while_armed_does_not_confirm(monkeypatch):
    unknown = PrLandingState(
        merged=False,
        closed=False,
        auto_merge_active=True,
        merge_state_status="unknown",
    )
    reads = _wire(monkeypatch, states=[unknown])
    verdict = _classify()
    assert verdict.kind == verdict_mod.PENDING
    assert "mergeStateStatus=UNKNOWN" in verdict.narrative
    assert len(reads) == 1


def test_closed_outranks_dirty(monkeypatch):
    closed_dirty = PrLandingState(
        merged=False,
        closed=True,
        auto_merge_active=False,
        merge_state_status="dirty",
    )
    _wire(monkeypatch, states=[closed_dirty, closed_dirty])
    verdict = _classify()
    assert verdict.kind == verdict_mod.CLOSED_UNMERGED
    assert "mergeStateStatus=DIRTY" in verdict.narrative
