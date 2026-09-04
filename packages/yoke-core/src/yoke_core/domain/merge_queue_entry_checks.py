"""Red required-check detection for a merge-queue landing.

The pull request's own required checks are the queue-entry gate: GitHub
will not enqueue until they pass, and it takes the latest run of each
required name. So one required check that has already concluded red means
the entry can never happen, whatever the rest of the set is still doing.
Without this terminal classification, the record reports a terminal verdict
as pending — the observed failure was thirteen minutes of "armed and
waiting" on a pull request that could never enqueue, because ``BLOCKED``
with everything else pending looks exactly like the ordinary wait.

Requiredness is what separates the two. A non-required check that fails
does not stop the entry, so only the required set is terminal, and a
rollup that cannot be read proves nothing either way. The server observer
writes that terminal result into the landing record; the waiting lane
consumes it without repeating the GitHub read.

A red set also makes the server observer disarm merge-when-ready so a later
green on the same pull request cannot auto-merge without this gate recording
a new verdict. Re-running ``yoke merge item`` after a fix re-arms as usual.
"""

from __future__ import annotations

from typing import Optional, Sequence

from yoke_core.engines.merge_worktree_pr_check_runs import LandingCheck
from yoke_core.engines.merge_worktree_pr_queue import (
    QueueEntryResult,
    leave_merge_queue,
)
from yoke_core.engines.merge_worktree_prepare import MergeContext

ENTRY_CHECKS_FAILED = "entry_checks_failed"

RED_CONCLUSIONS = frozenset(
    {
        "cancelled",
        "error",
        "failure",
        "startup_failure",
        "timed_out",
    }
)


def failed_required_checks(
    checks: Optional[Sequence[LandingCheck]],
) -> tuple[LandingCheck, ...]:
    """The required checks that already concluded red, name-sorted.

    Empty for a set with nothing red, and for a set that could not be
    read: an unreadable rollup is not evidence of a failure.
    """
    if not checks:
        return ()
    return tuple(
        sorted(
            (
                check
                for check in checks
                if check.required and check.conclusion in RED_CONCLUSIONS
            ),
            key=lambda check: check.name,
        )
    )


def describe_failed_checks(failed: Sequence[LandingCheck]) -> str:
    """The failed required checks and the runs that explain them."""
    return ", ".join(check.describe() for check in failed) or "none"


def regate_instruction(failed: Sequence[LandingCheck]) -> str:
    """Name the red required checks and what the holder does about them."""
    return (
        f"its required checks already concluded red "
        f"({describe_failed_checks(failed)}), so GitHub will not enqueue "
        "it — fix it on the lane, commit, re-run the verification gate, "
        "and re-run `yoke merge item`"
    )


def disarm_merge_when_ready(ctx: MergeContext, pr_num: str) -> str:
    """Disarm auto-merge; return a clause for the refusal, never raise."""
    result: QueueEntryResult = leave_merge_queue(ctx, pr_num)
    if result.success:
        return "merge-when-ready disarmed"
    detail = (result.error_detail or "disarm refused").strip()
    lowered = detail.lower()
    already_clear = "auto merge" in lowered and (
        "not enabled" in lowered
        or "not allowed" in lowered
        or "no auto merge" in lowered
    )
    if already_clear:
        return "merge-when-ready already cleared"
    return (
        f"merge-when-ready disarm failed: {detail}. Disable it on the "
        "pull request before pushing a fix, or GitHub may auto-merge the "
        "next green without this gate recording a verdict"
    )


def entry_checks_refusal(
    *,
    pr_num: str,
    head_sha: str,
    narrative: str,
    disarm_note: str,
    failed: Sequence[LandingCheck] = (),
) -> str:
    """Terminal red refusal: named checks, their runs, and the recovery."""
    sha = head_sha or "unreported"
    observed = narrative.strip() or f"pull request {pr_num}"
    return (
        f"entry-checks-failed: pull request {pr_num} head {sha} has "
        f"required checks that already concluded red "
        f"({describe_failed_checks(failed)}). GitHub will not enqueue it. "
        f"Observed {observed}. Fix on the lane, commit, re-run the "
        f"verification gate, and re-run `yoke merge item`. {disarm_note}"
    )


__all__ = [
    "ENTRY_CHECKS_FAILED",
    "RED_CONCLUSIONS",
    "describe_failed_checks",
    "disarm_merge_when_ready",
    "entry_checks_refusal",
    "failed_required_checks",
    "regate_instruction",
]
