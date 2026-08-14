"""Recover a landed standalone merge whose work claim was reclaimed."""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.api.function_call import ActorContext, TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain import standalone_item_merge_receipt as receipts
from yoke_core.domain.session_ambient_identity import resolve_ambient_session_id

_MISSING_CLAIM = "no live work claim on this item"


def _relay_error(response: Any, fallback: str) -> str:
    error = getattr(response, "error", None)
    return getattr(error, "message", None) or fallback if error else fallback


def _session_id(explicit: str) -> str:
    return explicit or str(resolve_ambient_session_id() or "")


def claim_error(item_id: int, session_id: str) -> str:
    """Empty when the caller owns the item claim, else the refusal."""
    response = call_dispatcher(
        function_id="claims.work.holder_get",
        target=TargetRef(kind="item", item_id=item_id),
    )
    if not response.success:
        return _relay_error(response, "work-claim holder lookup failed")
    holder = (response.result or {}).get("holder") or {}
    holder_session = str(holder.get("session_id") or "")
    if not holder_session:
        return f"{_MISSING_CLAIM}; acquire one with `yoke claims work acquire`"
    caller = _session_id(session_id)
    if not caller:
        return "ambient session identity is unavailable"
    if holder_session != caller:
        return f"work claim held by another session ({holder_session})"
    return ""


def claim_is_missing(error: str) -> bool:
    """Whether *error* specifically reports an unowned item."""
    return error.startswith(_MISSING_CLAIM)


def branch_needs_receipt(repo_root: str, branch: str) -> bool:
    """Whether close-out must reconstruct the pruned lane from its receipt."""
    return not git.branch_exists(repo_root, branch)


def reacquire_landed_claim(
    *,
    item_id: int,
    branch: str,
    target: str,
    repo_root: str,
    project: str,
    session_id: str,
) -> tuple[Optional[receipts.MergeReceipt], str]:
    """Reclaim close-out authority only after receipt and git agree."""
    receipt = receipts.load(
        item_id,
        branch,
        target,
        project=project,
    )
    if receipt is None or not receipt.commit_sha:
        return None, (
            f"{_MISSING_CLAIM}; no durable merge receipt proves a prior "
            "landing, so automatic work-claim recovery is refused"
        )
    landed = any(
        git.is_landed(repo_root, sha, target)
        for sha in (receipt.commit_sha, receipt.merge_sha)
        if sha
    )
    if not landed:
        return None, (
            "the durable merge receipt is not contained by "
            f"{target!r}; refusing automatic work-claim recovery"
        )
    caller = _session_id(session_id)
    if not caller:
        return None, "ambient session identity is unavailable"
    response = call_dispatcher(
        function_id="claims.work.acquire",
        target=TargetRef(kind="item", item_id=item_id),
        payload={
            "target": {"kind": "item", "item_id": item_id},
            "reason": "Converge landed merge close-out",
        },
        actor=ActorContext(session_id=caller),
        intent="landed merge close-out recovery",
    )
    if not response.success:
        return None, _relay_error(response, "work-claim recovery failed")
    return receipt, ""


def with_recorded_head(
    item: dict[str, Any],
    receipt: receipts.MergeReceipt,
) -> dict[str, Any]:
    """Present the receipt's verified lane head as the unique active lane."""
    return {
        **item,
        "worktrees": [{
            "state": "active",
            "branch": receipt.branch,
            "commit_sha": receipt.commit_sha,
        }],
    }


__all__ = [
    "branch_needs_receipt",
    "claim_error",
    "claim_is_missing",
    "reacquire_landed_claim",
    "with_recorded_head",
]
