"""What one observation of a queued pull request actually means.

Merging and ejection look identical from a single read. GitHub clears
merge-when-ready when the queue merges a pull request and when it drops
it, and the merged flag becomes visible a moment later, so a poll in
that window sees an unmerged, unarmed pull request. Nothing here is
terminal on one read except red required checks: checks on the
PR head that have already concluded failed/error/cancelled/timed_out
with nothing in flight. That cannot merge, so it must not spend the
poll budget. Other refusals still confirm: merged is re-read after a
short delay; a still-queued entry is still landing; only an unmerged,
open, unarmed, absent, failed-train PR has stalled. Every verdict names
the facts it saw, including ``mergeStateStatus`` so ``DIRTY`` is not a
silent wait.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from yoke_core.domain.github_poll_schedule import (
    MINIMUM_POLL_INTERVAL_SECONDS,
)
from yoke_core.engines.merge_worktree_pr_queue import (
    PrLandingState,
    QueueMember,
    TrainRun,
    read_pr_landing_state,
    read_queue_members,
    read_train_run,
)
from yoke_core.engines.merge_worktree_prepare import MergeContext
from yoke_core.domain.merge_queue_entry_checks import (
    ENTRY_CHECKS_FAILED,
    entry_checks_are_red,
)

# Queue ejection is a failed train, not an empty slot. GitHub clears the
# slot and merge-when-ready while a successful train is still merging.
_FAILED_TRAIN_CONCLUSIONS = frozenset(
    {"cancelled", "failure", "startup_failure", "timed_out"}
)


# What the pull request turned out to be doing.
LANDED = "landed"
CLOSED_UNMERGED = "closed_unmerged"
CONFLICTED = "conflicted"
STALLED = "stalled"
PENDING = "pending"

DEFAULT_CONFIRM_SECONDS = MINIMUM_POLL_INTERVAL_SECONDS


@dataclass(frozen=True)
class LandingCheck:
    """One check run attached to the SHA the train is validating."""

    name: str
    status: str
    conclusion: str = ""


@dataclass(frozen=True)
class LandingVerdict:
    """One classification of a queued pull request, with what it observed."""

    kind: str
    narrative: str = ""
    warnings: tuple[str, ...] = field(default=())
    head_sha: str = ""


def describe_checks(checks: Sequence[LandingCheck]) -> str:
    """Pending and concluded check names, sorted so a reshuffle is not news."""
    pending = sorted(check.name for check in checks if check.status != "completed")
    concluded = sorted(
        f"{check.name}={check.conclusion or check.status}"
        for check in checks
        if check.status == "completed"
    )
    return (
        f"pending-checks={','.join(pending) or 'none'} "
        f"concluded-checks={','.join(concluded) or 'none'}"
    )


def read_landing_checks(
    ctx: MergeContext,
    head_sha: str,
) -> tuple[Optional[tuple[LandingCheck, ...]], Optional[str]]:
    """Per-check breakdown for the SHA the train is validating."""
    from yoke_contracts.github_app_installation_permissions import (
        GITHUB_CHECKS_READ_PERMISSION_LEVELS as CHECKS_READ,
    )
    from yoke_core.domain.gh_rest_transport import (
        RestRequest,
        RestTransportError,
        request_with_retry,
        split_repo,
    )
    from yoke_core.engines.merge_worktree_pr_queue import resolve_auth_detail

    if not head_sha:
        return (), None
    auth, auth_err = resolve_auth_detail(ctx, CHECKS_READ)
    if auth_err or auth is None:
        return None, auth_err
    owner, repo = split_repo(auth.repo)
    try:
        response = request_with_retry(
            RestRequest(
                method="GET",
                path=f"/repos/{owner}/{repo}/commits/{head_sha}/check-runs",
            ),
            token=auth.token,
        )
    except RestTransportError as exc:
        return None, f"check-runs read failed: {exc}"
    payload = response.body if isinstance(response.body, dict) else None
    raw_runs = payload.get("check_runs") if payload is not None else None
    if not isinstance(raw_runs, list):
        return None, "check-runs response omitted check_runs"
    checks: list[LandingCheck] = []
    for raw in raw_runs:
        if not isinstance(raw, dict):
            return None, "check-runs response contained a malformed run"
        checks.append(
            LandingCheck(
                name=str(raw.get("name") or "unnamed check").strip(),
                status=str(raw.get("status") or "").strip().lower(),
                conclusion=str(raw.get("conclusion") or "").strip().lower(),
            )
        )
    return tuple(checks), None


def describe(
    pr_num: str,
    state: PrLandingState,
    entry: Optional[QueueMember],
    entry_readable: bool,
    train: Optional[TrainRun],
    checks: Optional[tuple[LandingCheck, ...]] = None,
) -> str:
    """The observed facts behind a verdict, as plain named readings."""
    if not entry_readable:
        slot = "unreadable"
    elif entry is None:
        slot = "absent"
    else:
        slot = entry.state or "present"
    if train is None:
        # Unidentified, not absent: the reader answers ``None`` both when the
        # lookup failed and when no queue ref carried this pull request's
        # marker, and naming either as a concluded run is the substitution
        # that put an unrelated train's green in an ejection report.
        run = "not identified"
    else:
        run = train.conclusion or train.status or "unreported"
        if train.url:
            run = f"{run} ({train.url})"
    merge_state = (state.merge_state_status or "").strip().upper() or "unreported"
    narrative = (
        f"pull request {pr_num}: merged=false, "
        f"state={'closed' if state.closed else 'open'}, "
        f"merge-when-ready={'armed' if state.auto_merge_active else 'cleared'}, "
        f"mergeStateStatus={merge_state}, "
        f"queue-entry={slot}, train-run={run}"
    )
    if checks is not None:
        narrative = f"{narrative}, {describe_checks(checks)}"
    return narrative


_Observe = tuple[
    str,
    Optional[QueueMember],
    bool,
    Optional[TrainRun],
    Optional[tuple[LandingCheck, ...]],
]


def _observe(
    ctx: MergeContext,
    pr_num: str,
    state: PrLandingState,
    target: str,
    warnings: list[str],
) -> _Observe:
    """Read the queue slot and train run behind ``state`` and describe them."""
    entry, entry_error = _queue_entry(ctx, pr_num, target)
    if entry_error:
        warnings.append(entry_error)
    train, train_note = read_train_run(ctx, pr_num)
    if train_note:
        warnings.append(train_note)
    checks: Optional[tuple[LandingCheck, ...]] = None
    check_sha = (train.head_sha if train is not None else "") or state.head_sha
    if check_sha:
        checks, check_error = read_landing_checks(ctx, check_sha)
        if check_error:
            warnings.append(check_error)
            checks = None
    narrative = describe(
        pr_num,
        state,
        entry,
        entry_error is None,
        train,
        checks,
    )
    return narrative, entry, entry_error is None, train, checks


def _queue_entry(
    ctx: MergeContext, pr_num: str, target: str
) -> tuple[Optional[QueueMember], Optional[str]]:
    """The queue's entry for ``pr_num``, if the queue can be read at all."""
    members, error = read_queue_members(ctx, base_branch=target)
    if error or members is None:
        return None, error or "queue membership unreadable"
    for member in members:
        if member.pr_num == str(pr_num):
            return member, None
    return None, None


def _has_conflicts(state: PrLandingState) -> bool:
    """GitHub ``DIRTY``: the merge commit cannot be created."""
    return state.merge_state_status.strip().lower() == "dirty"


def _failed_train(train: Optional[TrainRun]) -> bool:
    """The train concluded in a way that will not produce a merge."""
    if train is None:
        return False
    return (train.conclusion or "").strip().lower() in _FAILED_TRAIN_CONCLUSIONS


def classify_landing(
    ctx: MergeContext,
    *,
    pr_num: str,
    target: str,
    sleep: Callable[[float], None],
    confirm_seconds: float = DEFAULT_CONFIRM_SECONDS,
) -> LandingVerdict:
    """Decide what the pull request is doing, confirming before any refusal."""
    warnings: list[str] = []
    state, error = read_pr_landing_state(ctx, pr_num)
    if error:
        warnings.append(error)
    if state is None:
        return LandingVerdict(
            PENDING,
            narrative=f"pull request {pr_num}: unreadable this observation",
            warnings=tuple(warnings),
        )
    if state.merged:
        return LandingVerdict(
            LANDED,
            narrative=f"pull request {pr_num}: merged=true",
            warnings=tuple(warnings),
        )
    if state.auto_merge_active and not state.closed and not _has_conflicts(state):
        narrative, _entry, _readable, train, checks = _observe(
            ctx, pr_num, state, target, warnings
        )
        if train is None and entry_checks_are_red(checks):
            return LandingVerdict(
                ENTRY_CHECKS_FAILED,
                narrative=narrative,
                warnings=tuple(warnings),
                head_sha=state.head_sha,
            )
        return LandingVerdict(PENDING, narrative=narrative, warnings=tuple(warnings))

    # Unmerged and either closed, unarmed, or conflicted. A merge in
    # flight can look the same, so the reading is confirmed first.
    sleep(confirm_seconds)
    confirmed, confirm_error = read_pr_landing_state(ctx, pr_num)
    if confirm_error:
        warnings.append(confirm_error)
    if confirmed is None:
        return LandingVerdict(
            PENDING,
            narrative=f"pull request {pr_num}: unreadable this observation",
            warnings=tuple(warnings),
        )
    if confirmed.merged:
        return LandingVerdict(
            LANDED,
            narrative=f"pull request {pr_num}: merged=true",
            warnings=tuple(warnings),
        )

    narrative, entry, entry_readable, train, checks = _observe(
        ctx, pr_num, confirmed, target, warnings
    )
    if train is None and entry_checks_are_red(checks):
        return LandingVerdict(
            ENTRY_CHECKS_FAILED,
            narrative=narrative,
            warnings=tuple(warnings),
            head_sha=confirmed.head_sha,
        )
    if _has_conflicts(confirmed) and not confirmed.closed:
        return LandingVerdict(CONFLICTED, narrative=narrative, warnings=tuple(warnings))
    if not confirmed.closed:
        # An unreadable queue cannot prove the entry is gone. An entry that
        # is still there, or a train that has not failed, means GitHub is
        # still working — the slot and arming clear before merged=true.
        still_landing = (
            not entry_readable
            or entry is not None
            or confirmed.auto_merge_active
            or not _failed_train(train)
        )
        if still_landing:
            return LandingVerdict(
                PENDING, narrative=narrative, warnings=tuple(warnings)
            )
    return LandingVerdict(
        CLOSED_UNMERGED if confirmed.closed else STALLED,
        narrative=narrative,
        warnings=tuple(warnings),
    )


__all__ = [
    "CLOSED_UNMERGED",
    "CONFLICTED",
    "DEFAULT_CONFIRM_SECONDS",
    "ENTRY_CHECKS_FAILED",
    "LANDED",
    "LandingCheck",
    "LandingVerdict",
    "PENDING",
    "STALLED",
    "classify_landing",
    "describe",
    "describe_checks",
    "read_landing_checks",
]
