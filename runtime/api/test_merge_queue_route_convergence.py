"""A queue landing converges on whatever the pull request actually did.

The queue merges on GitHub whether or not the process watching it survives,
and it clears merge-when-ready both when it merges a pull request and when it
drops one. Every case here is a landing that already happened, or is about to,
being read by a process that must not mistake it for a failure — and the one
genuine stall, which has to stay diagnosable.
"""

import pytest

from runtime.api.merge_queue_landing_test_helpers import (
    ARMED,
    CLOSED,
    MERGED,
    UNARMED,
    land,
    wire_happy_path,
)

from yoke_core.domain import merge_queue_landing_outcome as outcome_mod
from yoke_core.domain import merge_queue_landing_verdict as verdict_mod
from yoke_core.domain import merge_queue_landing_pull_request as landing_pr_mod
from yoke_core.domain import merge_queue_route as route_mod
from yoke_core.domain.merge_queue_close_out import QueueCloseOut
from yoke_core.engines.merge_worktree_pr_queue import (
    PrLandingState,
    QueueEntryResult,
    QueueMember,
    TrainRun,
)
from yoke_core.engines.merge_worktree_pr_rest import PrCreateResult


def test_stalled_landing_names_every_fact_it_observed(monkeypatch):
    wire_happy_path(
        monkeypatch,
        landing_states=[ARMED, UNARMED, UNARMED],
        queue_entries=(),
        train=TrainRun(
            status="completed", conclusion="failure", url="https://runs/9",
        ),
    )
    outcome = land()
    assert not outcome.ok
    assert outcome.exit_code == route_mod.RECOVERABLE_QUEUE_EXIT_CODE
    assert "no longer driving pull request 42" in outcome.error
    assert "state=open" in outcome.error
    assert "merge-when-ready=cleared" in outcome.error
    assert "queue-entry=absent" in outcome.error
    assert "train-run=failure (https://runs/9)" in outcome.error
    assert "mergeStateStatus=unreported" in outcome.error
    # The verdict that sent an operator to inspect a green run asserted
    # something about checks it had never read.
    assert "failed train checks" not in outcome.error


def test_cleared_arming_while_the_train_validates_keeps_polling(monkeypatch):
    wire_happy_path(
        monkeypatch,
        landing_states=[ARMED, UNARMED, UNARMED, MERGED],
        queue_entries=(
            QueueMember(
                pr_num="42", head_ref="YOK-200", state="AWAITING_CHECKS",
            ),
        ),
    )
    outcome = land()
    assert outcome.ok
    assert outcome.exit_code == 0


def test_green_train_with_cleared_slot_still_converges(monkeypatch):
    """GitHub drops the slot before merged=true; that is not a stall."""
    wire_happy_path(
        monkeypatch,
        landing_states=[ARMED, UNARMED, UNARMED, MERGED],
        queue_entries=(),
        train=TrainRun(
            status="completed", conclusion="success", url="https://runs/3",
        ),
    )
    outcome = land()
    assert outcome.ok
    assert outcome.exit_code == 0


def test_merge_during_the_confirmation_read_converges(monkeypatch):
    """Merging clears arming too; the confirming read tells them apart."""
    wire_happy_path(monkeypatch, landing_states=[ARMED, UNARMED, MERGED])

    def forbidden(_ctx, base_branch="main"):
        raise AssertionError("a merged PR needs no queue-membership read")

    monkeypatch.setattr(verdict_mod, "read_queue_members", forbidden)
    assert land().ok


def test_unreadable_queue_never_classifies_a_stall(monkeypatch):
    wire_happy_path(
        monkeypatch, landing_states=[ARMED, UNARMED, UNARMED, MERGED],
    )
    monkeypatch.setattr(
        verdict_mod, "read_queue_members",
        lambda _ctx, base_branch="main": (None, "queue read failed"),
    )
    outcome = land()
    assert outcome.ok
    assert "queue read failed" in outcome.warnings


def test_closed_unmerged_is_terminal(monkeypatch):
    wire_happy_path(
        monkeypatch,
        landing_states=[ARMED, CLOSED, CLOSED],
        train=TrainRun(status="completed", conclusion="cancelled"),
    )
    outcome = land()
    assert not outcome.ok
    assert outcome.exit_code == 1
    assert "closed without merging" in outcome.error
    assert "state=closed" in outcome.error
    assert "train-run=cancelled" in outcome.error


def test_reentry_with_merged_pr_skips_queue_entry(monkeypatch):
    wire_happy_path(monkeypatch)

    def forbidden_entry(_ctx, pr_num):
        raise AssertionError("must not re-enter an already-merged PR")

    monkeypatch.setattr(route_mod, "enter_merge_queue", forbidden_entry)
    outcome = land()
    assert outcome.ok
    assert outcome.already_merged


def test_reentry_with_armed_pr_skips_entry_and_polls(monkeypatch):
    wire_happy_path(monkeypatch, landing_states=[ARMED, MERGED])

    def forbidden_entry(_ctx, pr_num):
        raise AssertionError("must not re-arm merge-when-ready")

    monkeypatch.setattr(route_mod, "enter_merge_queue", forbidden_entry)
    assert land().ok


def test_the_landing_enqueues_the_pull_request_the_gate_opened(monkeypatch):
    """The gate leaves an open, green, unarmed pull request at the lane head.

    The landing must arm that one rather than opening a second — a second
    pull request for the same head is what would put two entry runs and two
    queue members behind one item.
    """
    wire_happy_path(monkeypatch, landing_states=[UNARMED, MERGED])

    def forbidden(*_a, **_kw):
        raise AssertionError("the gate's pull request must be reused")

    monkeypatch.setattr(landing_pr_mod, "create_pr", forbidden)
    entered: list[str] = []
    monkeypatch.setattr(
        route_mod, "enter_merge_queue",
        lambda _ctx, pr_num: entered.append(pr_num) or QueueEntryResult(
            success=True,
        ),
    )

    outcome = land()

    assert outcome.ok
    assert outcome.pr_num == "42"
    assert entered == ["42"]


def test_reentry_after_the_queue_merged_never_opens_a_second_pr(monkeypatch):
    """The lookup sees merged pull requests, so no create is attempted."""
    wire_happy_path(monkeypatch)

    def forbidden(*_a, **_kw):
        raise AssertionError("a merged PR must not be recreated or re-entered")

    monkeypatch.setattr(landing_pr_mod, "create_pr", forbidden)
    monkeypatch.setattr(route_mod, "enter_merge_queue", forbidden)
    outcome = land()
    assert outcome.ok
    assert outcome.pr_num == "42"


@pytest.mark.parametrize("refusal", ["already_exists", "no_commits"])
def test_recoverable_create_refusals_rediscover_the_pull_request(
    monkeypatch, refusal,
):
    wire_happy_path(monkeypatch)
    found = [(None, None, ""), ("url", "42", "")]
    monkeypatch.setattr(
        landing_pr_mod, "find_landable_pull_request",
        lambda _ctx, lane_head="": found.pop(0),
    )
    monkeypatch.setattr(
        landing_pr_mod, "create_pr",
        lambda _ctx, **_kw: PrCreateResult(
            pr_url="", pr_num="", **{refusal: True},
        ),
    )
    outcome = land()
    assert outcome.ok
    assert outcome.pr_num == "42"


def test_lane_beyond_the_merged_pull_request_lands_freshly(monkeypatch):
    """A declined stale pull request routes to a landing of its own.

    The lane picked up commits after its pull request merged, so the merge
    commit that pull request produced answers for none of them. Everything
    the landing records has to name the new pull request instead.
    """
    wire_happy_path(monkeypatch, landing_states=[UNARMED, MERGED])
    monkeypatch.setattr(
        landing_pr_mod, "find_landable_pull_request",
        lambda _ctx, lane_head="": (None, None, "pull request 42 merged head"),
    )
    monkeypatch.setattr(
        landing_pr_mod, "create_pr",
        lambda _ctx, **_kw: PrCreateResult(pr_url="https://gh/99", pr_num="99"),
    )
    entered: list[str] = []
    monkeypatch.setattr(
        route_mod, "enter_merge_queue",
        lambda _ctx, pr_num: entered.append(pr_num) or QueueEntryResult(
            success=True, pr_num=pr_num,
        ),
    )
    landed: list[str] = []
    monkeypatch.setattr(
        outcome_mod, "record_landing",
        lambda _ctx, **kw: landed.append(kw["pr_num"]) or QueueCloseOut(
            merge_sha="n" * 40, touched_files=("a.py",),
        ),
    )

    outcome = land()

    assert outcome.ok
    assert outcome.pr_num == "99"
    assert not outcome.already_merged
    assert entered == ["99"]
    assert landed == ["99"]


def test_lane_beyond_the_merged_pull_request_records_nothing_when_stuck(
    monkeypatch,
):
    """Nothing is recorded when the fresh landing cannot open its own."""
    wire_happy_path(monkeypatch)
    monkeypatch.setattr(
        landing_pr_mod, "find_landable_pull_request",
        lambda _ctx, lane_head="": (
            None, None, "pull request 42 merged head aaaa, not the lane head bbbb",
        ),
    )
    monkeypatch.setattr(
        landing_pr_mod, "create_pr",
        lambda _ctx, **_kw: PrCreateResult(
            pr_url="", pr_num="", no_commits=True,
        ),
    )

    def forbidden(*_a, **_kw):
        raise AssertionError("a refused convergence must record nothing")

    monkeypatch.setattr(outcome_mod, "record_landing", forbidden)

    outcome = land()

    assert not outcome.ok
    assert "carries commits beyond the pull request that merged it" in outcome.error
    assert "not the lane head bbbb" in outcome.error


def test_no_commits_without_any_pull_request_is_named(monkeypatch):
    wire_happy_path(monkeypatch)
    monkeypatch.setattr(
        landing_pr_mod, "find_landable_pull_request",
        lambda _ctx, lane_head="": (None, None, ""),
    )
    monkeypatch.setattr(
        landing_pr_mod, "create_pr",
        lambda _ctx, **_kw: PrCreateResult(
            pr_url="", pr_num="", no_commits=True,
        ),
    )
    outcome = land()
    assert not outcome.ok
    assert "no commits against" in outcome.error
    assert "YOK-200" in outcome.error


def test_dirty_pull_request_names_rebase_and_does_not_keep_waiting(monkeypatch):
    dirty = PrLandingState(
        merged=False, closed=False, auto_merge_active=True,
        merge_state_status="dirty",
    )
    wire_happy_path(
        monkeypatch,
        landing_states=[ARMED, dirty, dirty],
        queue_entries=(),
    )
    announced: list[str] = []
    outcome = land(emit=announced.append)
    assert not outcome.ok
    assert outcome.exit_code == route_mod.RECOVERABLE_QUEUE_EXIT_CODE
    assert "merge conflicts" in outcome.error
    assert "rebase the lane onto main" in outcome.error
    assert "re-run the verification gate" in outcome.error
    assert "yoke merge item" in outcome.error
    assert "Re-running the landing is safe" not in outcome.error
    assert "mergeStateStatus=DIRTY" in outcome.error
    assert any("mergeStateStatus=DIRTY" in line for line in announced)


def test_poll_announces_a_merge_state_status_transition(monkeypatch):
    dirty = PrLandingState(
        merged=False, closed=False, auto_merge_active=True,
        merge_state_status="dirty",
    )
    wire_happy_path(
        monkeypatch,
        landing_states=[ARMED, ARMED, dirty, dirty],
        queue_entries=(),
    )
    announced: list[str] = []
    outcome = land(emit=announced.append)
    assert not outcome.ok
    assert any("mergeStateStatus=unreported" in line for line in announced)
    assert any("mergeStateStatus=DIRTY" in line for line in announced)
    assert announced[0] != announced[-1]
