"""A handoff is recorded only once GitHub says it holds the landing."""

from __future__ import annotations

from yoke_core.domain.merge_queue_enqueue_verification import (
    ADMISSION_CONFIRM_SECONDS,
    verify_landing_admitted,
)
from yoke_core.engines.merge_worktree_pr_membership import PrQueueMembership
from yoke_core.engines.merge_worktree_pr_queue import PrLandingState
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext


CTX = MergeContext(args=MergeArgs(branch="ALP-1"), repo_root="", project="alpha")

QUEUED = PrQueueMembership(in_queue=True, entry_state="QUEUED", mergeable="MERGEABLE")
NOT_QUEUED = PrQueueMembership(in_queue=False, mergeable="MERGEABLE")
CONFLICTING = PrQueueMembership(in_queue=False, mergeable="CONFLICTING")

#: Armed, eligible, and waiting on its own required checks. GitHub creates
#: the queue entry only once those pass, so this is the ordinary landing.
ARMED_AWAITING_CHECKS = PrLandingState(
    merged=False,
    closed=False,
    auto_merge_active=True,
    merge_state_status="blocked",
)
DIRTY = PrLandingState(
    merged=False,
    closed=False,
    auto_merge_active=True,
    merge_state_status="dirty",
)
NEVER_ARMED = PrLandingState(
    merged=False,
    closed=False,
    auto_merge_active=False,
    merge_state_status="clean",
)
MERGED = PrLandingState(merged=True, closed=True, auto_merge_active=False)


def _scripted(*results):
    """A reader that serves each result once, then repeats the last."""
    remaining = list(results)

    def read(_ctx, _pr_num):
        if len(remaining) > 1:
            return remaining.pop(0)
        return remaining[0]

    return read


def _verify(*, membership, state, sleep=lambda _s: None, target="main"):
    return verify_landing_admitted(
        CTX,
        "42",
        target=target,
        sleep=sleep,
        read_membership=membership,
        read_state=state if callable(state) else _scripted((state, None)),
    )


def test_an_armed_pull_request_awaiting_its_checks_is_admitted():
    """The queue entry appears only after the checks pass; that is not a defect."""
    slept: list[float] = []

    refusal = _verify(
        membership=_scripted((NOT_QUEUED, None)),
        state=ARMED_AWAITING_CHECKS,
        sleep=slept.append,
    )

    assert refusal == ""
    assert slept == []


def test_a_queued_pull_request_is_admitted():
    assert _verify(membership=_scripted((QUEUED, None)), state=NEVER_ARMED) == ""


def test_an_arming_that_settles_on_the_confirm_read_is_admitted():
    slept: list[float] = []

    refusal = _verify(
        membership=_scripted((NOT_QUEUED, None)),
        state=_scripted((NEVER_ARMED, None), (ARMED_AWAITING_CHECKS, None)),
        sleep=slept.append,
    )

    assert refusal == ""
    assert slept == [ADMISSION_CONFIRM_SECONDS]


def test_an_arming_that_never_took_is_refused():
    refusal = _verify(membership=_scripted((NOT_QUEUED, None)), state=NEVER_ARMED)

    assert "was not taken by the merge queue" in refusal
    assert "neither armed nor queued" in refusal
    assert "merge-when-ready=cleared" in refusal
    assert "isInMergeQueue=false" in refusal


def test_a_dirty_pull_request_is_refused_even_while_armed():
    """Arming survives a base that moved; the ability to merge does not."""
    refusal = _verify(
        membership=_scripted((CONFLICTING, None)), state=DIRTY, target="trunk"
    )

    assert "conflicts with its base branch" in refusal
    assert "rebase the lane onto trunk" in refusal
    assert "mergeStateStatus=DIRTY" in refusal


def test_a_merge_between_the_reads_is_not_a_refusal():
    refusal = _verify(membership=_scripted((NOT_QUEUED, None)), state=MERGED)

    assert refusal == ""


def test_an_unreadable_membership_refuses_rather_than_reporting_enqueued():
    refusal = _verify(
        membership=_scripted((None, "github graphql transport failure")),
        state=ARMED_AWAITING_CHECKS,
    )

    assert "could not be read" in refusal
    assert "github graphql transport failure" in refusal
