"""Read-only queue gates shared by landing and its readiness report."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from yoke_contracts.runtime_ports.structured_dispatch import get_structured_dispatch
from yoke_core.domain.merge_context import MergeArgs, MergeContext
from yoke_core.domain.merge_github_discovery import list_branch_pull_requests
from yoke_core.domain.merge_github_queue import (
    read_queue_members,
    read_pr_landing_state,
)
from yoke_core.domain.merge_github_train_run import TrainRun, read_train_run
from yoke_core.domain.merge_queue_admission import evaluate_admission
from yoke_core.domain.merge_queue_admission_shape import candidate_shape, train_context
from yoke_core.domain.merge_queue_failed_train import unchanged_failed_train_refusal


@dataclass(frozen=True)
class QueueGate:
    refusal: str = ""
    unreadable: str = ""
    member_refs: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


def queue_admission_refusals(
    ctx: MergeContext,
    *,
    public_ref: str,
    target: str,
    gate: Literal["composition", "failed train"] = "composition",
    dispatch: Callable[..., Any] | None = None,
    pr_num: str = "",
    lane_head: str = "",
    train: TrainRun | None = None,
) -> QueueGate:
    """Ask one gate at its landing boundary without moving or publishing anything.

    Composition runs before PR publication; failed-train replay runs just
    before enqueue. Keeping those boundaries preserves landing's ordering.
    Read failures stay distinct so --check can defer them to the merge.
    """
    if gate == "failed train":
        refusal = (
            unchanged_failed_train_refusal(
                ctx,
                pr_num,
                lane_head=lane_head,
                base_branch=target,
                train=train,
            )
            if pr_num
            else ""
        )
        return QueueGate(refusal=refusal or "")
    dispatch = dispatch or get_structured_dispatch().call_dispatcher
    members, error = read_queue_members(ctx, base_branch=target)
    if error or members is None:
        return QueueGate(unreadable=error or "queue unreadable")
    refs = tuple(
        m.head_ref for m in members if m.head_ref and m.head_ref != ctx.args.branch
    )
    candidate, error = candidate_shape(dispatch, public_ref)
    if error:
        return QueueGate(unreadable=error, member_refs=refs)
    context, error = train_context(dispatch, public_ref, refs, ctx.project)
    if error:
        return QueueGate(unreadable=error, member_refs=refs)
    verdict = evaluate_admission(candidate, context)
    return QueueGate(
        refusal="" if verdict.admit else verdict.narrative(),
        member_refs=refs,
        notes=context.notes,
    )


def check_queue_gates(readiness: Any, *, item: dict[str, Any], head: str) -> None:
    """Read both queue gates for --check, with no PR creation or writes."""
    from yoke_core.domain.merge_landing_readiness import LandingBlocker

    ctx = MergeContext(
        args=MergeArgs(branch=readiness.branch, target=readiness.target),
        repo_root=str(readiness.repo_root),
        project=str((item.get("project") or {}).get("slug") or ""),
        item_id=readiness.public_ref,
        public_ref=readiness.public_ref,
    )
    result = queue_admission_refusals(
        ctx,
        public_ref=readiness.public_ref,
        target=readiness.target,
    )
    if result.refusal:
        readiness.blockers.append(LandingBlocker("queue admission", result.refusal))
    if result.unreadable:
        readiness.merge_will.append(f"recheck queue admission: {result.unreadable}")
    readiness.merge_will.extend(f"recheck queue context: {note}" for note in result.notes)
    listing = list_branch_pull_requests(
        ctx, query={"state": "all", "base": readiness.target, "sort": "updated", "direction": "desc"}
    )
    if listing.error:
        readiness.merge_will.append(
            f"resolve the landing pull request: {listing.error}"
        )
        return
    if not listing.rows:
        return
    open_rows = [row for row in listing.rows if row.get("state") == "open"]
    pr_num = str((open_rows or listing.rows)[0].get("number") or "")
    if not pr_num:
        readiness.merge_will.append(
            "resolve the landing pull request: listing omitted its number"
        )
        return
    state, error = read_pr_landing_state(ctx, pr_num)
    if error:
        readiness.merge_will.append(f"recheck pull request {pr_num}: {error}")
        return
    if state is not None and (
        state.merged or (not state.closed and state.auto_merge_active)
    ):
        return
    train, note = read_train_run(ctx, pr_num)
    # A pull request that was never queued has no train; that is not news.
    if note and not note.no_run_found:
        readiness.merge_will.append(
            f"train lookup unavailable for pull request {pr_num}: {note}"
        )
    if train is None:
        return
    result = queue_admission_refusals(
        ctx,
        public_ref=readiness.public_ref,
        target=readiness.target,
        train=train,
        gate="failed train",
        pr_num=pr_num,
        lane_head=head,
    )
    if result.refusal:
        readiness.blockers.append(LandingBlocker("failed train", result.refusal))
