"""Queue-routed landing for a verified item branch.

The standalone engine merges locally under the merge lock; this route
lands the same branch through the GitHub merge queue instead: admission
control against current queue membership, PR ensure + merge-when-ready
entry, a poll on the PR's merged state while the queue validates the
train's combined head server-side, then the member's close-out — the
``merged_at`` stamp and the batch verification receipt. Lifecycle status
and GitHub sync stay caller-owned, exactly as they are for the
standalone engine, so both routes drive the same downstream gates.

No lock wraps any of this: the expensive gate runs inside GitHub, and
the Yoke-side close-out is one short bookkeeping step per member.
Every refusal is named — an unreachable or unconfigured queue is an
error the caller surfaces, never a silent downgrade to a local merge.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from yoke_contracts.api.function_call import TargetRef

from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.json_helper import loads_text
from yoke_core.domain.merge_queue_admission import (
    TrainCandidate,
    TrainContext,
    evaluate_admission,
)
from yoke_core.domain.merge_queue_batch_receipt import (
    BatchReceipt,
    observe_batch,
    record_batch_evidence,
)
from yoke_core.domain.standalone_item_merge import (
    stamp_merged_at,
)
from yoke_core.engines.merge_worktree_pr_queue import (
    enter_merge_queue,
    read_pr_landing_state,
    read_queue_members,
)
from yoke_core.engines.merge_worktree_pr_rest import (
    create_pr,
    find_existing_pr,
)
from yoke_core.engines.merge_worktree_prepare import MergeContext


# Admission refusals and queue ejections are retry-later outcomes, the
# same recoverable class as the standalone engine's held merge lock.
RECOVERABLE_QUEUE_EXIT_CODE = 7

DEFAULT_POLL_SECONDS = 30.0
DEFAULT_DEADLINE_SECONDS = 45.0 * 60.0

_NON_TERMINAL_CLAIM_STATES = ("planned", "active", "blocked")


@dataclass(frozen=True)
class QueueLandingOutcome:
    """What one queue-routed landing attempt produced."""

    ok: bool
    exit_code: int
    pr_num: str = ""
    merge_sha: str = ""
    batch: Optional[BatchReceipt] = None
    error: str = ""
    warnings: tuple[str, ...] = field(default=())


def _dispatch_read(
    dispatch: Callable[..., Any],
    *,
    function_id: str,
    item_ref: str,
    payload: dict[str, Any],
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    response = dispatch(
        function_id=function_id,
        target=TargetRef(kind="item", item_ref=item_ref),
        payload=payload,
    )
    if getattr(response, "success", False):
        result = getattr(response, "result", None)
        return (result if isinstance(result, dict) else {}), None
    error = getattr(response, "error", None)
    message = getattr(error, "message", None) or f"{function_id} failed"
    return None, f"{function_id}({item_ref}): {message}"


def _candidate_shape(
    dispatch: Callable[..., Any], item_ref: str
) -> tuple[Optional[TrainCandidate], Optional[str]]:
    """Resolve one item's admission shape through registered reads."""
    claims_result, claims_err = _dispatch_read(
        dispatch,
        function_id="claims.path.list",
        item_ref=item_ref,
        payload={},
    )
    if claims_err:
        return None, claims_err
    target_ids: set[int] = set()
    for claim in (claims_result or {}).get("claims") or []:
        if not isinstance(claim, dict):
            continue
        if str(claim.get("state") or "") not in _NON_TERMINAL_CLAIM_STATES:
            continue
        for target_id in claim.get("target_ids") or []:
            try:
                target_ids.add(int(target_id))
            except (TypeError, ValueError):
                continue
    profile_result, profile_err = _dispatch_read(
        dispatch,
        function_id="items.get.run",
        item_ref=item_ref,
        payload={"fields": ["db_mutation_profile"]},
    )
    if profile_err:
        return None, profile_err
    raw_profile = (profile_result or {}).get("db_mutation_profile") or ""
    carrier = False
    if raw_profile:
        try:
            parsed = loads_text(str(raw_profile))
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            carrier = str(parsed.get("state") or "none") != "none"
    return (
        TrainCandidate(
            item_ref=item_ref,
            claimed_target_ids=frozenset(target_ids),
            migration_carrier=carrier,
        ),
        None,
    )


def _train_context(
    dispatch: Callable[..., Any],
    candidate_ref: str,
    member_refs: tuple[str, ...],
) -> tuple[Optional[TrainContext], Optional[str]]:
    members: list[TrainCandidate] = []
    for ref in member_refs:
        shape, err = _candidate_shape(dispatch, ref)
        if err:
            return None, err
        members.append(shape)
    deps_result, deps_err = _dispatch_read(
        dispatch,
        function_id="shepherd.dependency_list.run",
        item_ref=candidate_ref,
        payload={},
    )
    if deps_err:
        return None, deps_err
    attested: set[str] = set()
    serial: set[str] = set()
    for row in (deps_result or {}).get("dependencies") or []:
        if not isinstance(row, dict):
            continue
        dependent = str(row.get("dependent_item") or "")
        blocking = str(row.get("blocking_item") or "")
        other = blocking if dependent == candidate_ref else dependent
        if not other or other == candidate_ref:
            continue
        if str(row.get("gate_point") or "") == "coordination_only":
            attested.add(other)
        else:
            serial.add(other)
    return (
        TrainContext(
            members=tuple(members),
            coordination_attested_refs=frozenset(attested),
            serial_linked_refs=frozenset(serial),
        ),
        None,
    )


def _ensure_pr(ctx: MergeContext, item_ref: str) -> tuple[str, Optional[str]]:
    """Find or create the item's PR; returns ``(pr_num, error)``."""
    _, pr_num = find_existing_pr(ctx)
    if pr_num:
        return pr_num, None
    created = create_pr(
        ctx,
        title=f"{item_ref}: merge queue landing",
        body=(
            f"Item branch for {item_ref}; lands through the merge queue's "
            "merge_group integration gate."
        ),
    )
    if created.pr_num:
        return created.pr_num, None
    return "", created.error_detail or "pull request create failed"


def land_item_through_merge_queue(
    ctx: MergeContext,
    *,
    item_id: int,
    item_ref: str,
    target: str = "main",
    dispatch: Callable[..., Any] = call_dispatcher,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    deadline_seconds: float = DEFAULT_DEADLINE_SECONDS,
) -> QueueLandingOutcome:
    """Land one verified item branch through the merge queue."""
    warnings: list[str] = []

    members, members_err = read_queue_members(ctx, base_branch=target)
    if members_err or members is None:
        return QueueLandingOutcome(
            ok=False, exit_code=1, error=members_err or "queue unreadable"
        )
    member_refs = tuple(
        member.head_ref for member in members
        if member.head_ref and member.head_ref != ctx.args.branch
    )

    candidate, candidate_err = _candidate_shape(dispatch, item_ref)
    if candidate_err:
        return QueueLandingOutcome(
            ok=False, exit_code=1, error=candidate_err
        )
    context, context_err = _train_context(dispatch, item_ref, member_refs)
    if context_err:
        return QueueLandingOutcome(ok=False, exit_code=1, error=context_err)
    verdict = evaluate_admission(candidate, context)
    if not verdict.admit:
        return QueueLandingOutcome(
            ok=False,
            exit_code=RECOVERABLE_QUEUE_EXIT_CODE,
            error=verdict.narrative(),
        )

    pr_num, pr_err = _ensure_pr(ctx, item_ref)
    if pr_err:
        return QueueLandingOutcome(ok=False, exit_code=1, error=pr_err)
    entry = enter_merge_queue(ctx, pr_num)
    if not entry.success:
        return QueueLandingOutcome(
            ok=False,
            exit_code=1,
            pr_num=pr_num,
            error=entry.error_detail or "queue entry refused",
        )

    deadline = monotonic() + deadline_seconds
    merged = False
    while monotonic() < deadline:
        state, state_err = read_pr_landing_state(ctx, pr_num)
        if state_err:
            warnings.append(state_err)
        elif state is not None:
            if state.merged:
                merged = True
                break
            if state.closed:
                return QueueLandingOutcome(
                    ok=False,
                    exit_code=1,
                    pr_num=pr_num,
                    error=(
                        f"pull request {pr_num} closed without merging; "
                        "reopen or recreate it before re-entering the queue"
                    ),
                    warnings=tuple(warnings),
                )
            if not state.auto_merge_active:
                return QueueLandingOutcome(
                    ok=False,
                    exit_code=RECOVERABLE_QUEUE_EXIT_CODE,
                    pr_num=pr_num,
                    error=(
                        f"the merge queue ejected pull request {pr_num} "
                        "(merge-when-ready cleared while unmerged) — inspect "
                        "the failed train checks, fix, and re-enter the queue"
                    ),
                    warnings=tuple(warnings),
                )
        sleep(poll_seconds)
    if not merged:
        return QueueLandingOutcome(
            ok=False,
            exit_code=RECOVERABLE_QUEUE_EXIT_CODE,
            pr_num=pr_num,
            error=(
                f"pull request {pr_num} did not merge within "
                f"{int(deadline_seconds)}s; inspect the queue position and "
                "train checks, then re-run the landing to resume polling"
            ),
            warnings=tuple(warnings),
        )

    stamp_error = stamp_merged_at(item_id)
    if stamp_error:
        warnings.append(f"merged_at not recorded: {stamp_error}")
    snapshot = tuple(dict.fromkeys((*member_refs, item_ref)))
    receipt, receipt_warn = observe_batch(
        ctx, pr_num=pr_num, member_snapshot=snapshot
    )
    if receipt_warn:
        warnings.append(receipt_warn)
    if receipt is not None:
        record_error = record_batch_evidence(item_id, receipt)
        if record_error:
            warnings.append(f"batch evidence not recorded: {record_error}")
    return QueueLandingOutcome(
        ok=True,
        exit_code=0,
        pr_num=pr_num,
        merge_sha=(receipt.merge_sha if receipt else ""),
        batch=receipt,
        warnings=tuple(warnings),
    )


__all__ = [
    "DEFAULT_DEADLINE_SECONDS",
    "DEFAULT_POLL_SECONDS",
    "RECOVERABLE_QUEUE_EXIT_CODE",
    "QueueLandingOutcome",
    "land_item_through_merge_queue",
]
