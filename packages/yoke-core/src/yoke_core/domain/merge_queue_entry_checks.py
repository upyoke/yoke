"""Red required-check detection for a merge-queue landing poll.

The pull request's own required checks are the queue-entry gate: GitHub
will not enqueue until they pass. When those checks have already
concluded red and nothing is still in flight for that head sha, further
polling cannot produce a merge. Returning a poll-budget timeout in that
state reports a terminal verdict as pending.

A red set also disarms merge-when-ready so a later green on the same
pull request cannot auto-merge without this gate recording a new verdict.
Re-running ``yoke merge item`` after a fix re-arms as usual.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

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


def entry_checks_are_red(
    checks: Optional[Sequence[Any]],
) -> bool:
    """True when a completed check set has a red conclusion and none pending."""
    if not checks:
        return False
    if any(check.status != "completed" for check in checks):
        return False
    return any(check.conclusion in RED_CONCLUSIONS for check in checks)


def failed_entry_check_names(
    checks: Optional[Sequence[Any]],
) -> tuple[str, ...]:
    """Check names that already concluded red, sorted for stable narrative."""
    if not checks:
        return ()
    return tuple(
        sorted(
            check.name
            for check in checks
            if check.status == "completed" and check.conclusion in RED_CONCLUSIONS
        )
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
    failed_names: Sequence[str] = (),
) -> str:
    """Terminal red refusal: named checks, recovery, and disarm outcome."""
    failed = ",".join(failed_names) or "named in the observation"
    sha = head_sha or "unreported"
    observed = narrative.strip() or f"pull request {pr_num}"
    return (
        f"entry-checks-failed: pull request {pr_num} head {sha} has "
        f"required checks that already concluded red with nothing in "
        f"flight ({failed}). GitHub will not enqueue it. Observed "
        f"{observed}. Fix on the lane, commit, and re-run "
        f"`yoke merge item`. {disarm_note}"
    )


__all__ = [
    "ENTRY_CHECKS_FAILED",
    "RED_CONCLUSIONS",
    "disarm_merge_when_ready",
    "entry_checks_are_red",
    "entry_checks_refusal",
    "failed_entry_check_names",
]
