"""Registered hold of one item's live merge-queue candidate."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class MergeQueueHoldRequest(BaseModel):
    """The item target carries the landing identity."""


class MergeQueueHoldResponse(BaseModel):
    item_id: int
    public_ref: str
    project: str
    outcome: str
    held: bool
    pr_number: str
    target: str
    actions: List[str] = Field(default_factory=list)
    before: Optional[Dict[str, Any]] = None
    after: Optional[Dict[str, Any]] = None
    merged: bool = False
    merge_commit_sha: str = ""
    merged_at: str = ""
    refusal: str = ""
    narrative: str


def _error(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def handle_hold(request: FunctionCallRequest) -> HandlerOutcome:
    """Disarm and dequeue the item's candidate, then verify both cleared."""
    if request.target.kind != "item" or request.target.item_id is None:
        return _error(
            "target_invalid",
            "github.merge_queue.hold requires a resolved item target",
            "$.target",
        )

    from yoke_core.domain.item_detail_read import get_item_detail
    from yoke_core.domain.merge_queue_hold import hold_landing
    from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext

    try:
        item = get_item_detail(int(request.target.item_id))
    except LookupError as exc:
        return _error("not_found", str(exc), "$.target.item_id")

    project = item.get("project") or {}
    public_ref = str(item.get("public_ref") or request.target.item_id)
    target = str(project.get("default_branch") or "main")
    pr_number = str((item.get("merge_queue") or {}).get("pr_number") or "")
    if not pr_number:
        return _error(
            "no_landing_recorded",
            (
                f"{public_ref} records no landing pull request, so there is no "
                "queue candidate to hold. Confirm the landing with "
                f"`yoke github merge-queue readiness {public_ref}`; a lane that "
                "never reached a pull request has nothing armed."
            ),
            "$.target.item_id",
        )

    hold = hold_landing(
        MergeContext(
            args=MergeArgs(branch="", target=target),
            project=str(project.get("slug") or ""),
        ),
        pr_number=pr_number,
        target=target,
    )
    result: Dict[str, Any] = {
        "item_id": int(item["id"]),
        "public_ref": public_ref,
        "project": str(project.get("slug") or ""),
        **hold.to_dict(),
    }
    if not hold.held:
        return HandlerOutcome(
            result_payload=result,
            primary_success=False,
            error=FunctionError(
                code=hold.outcome,
                message=hold.describe(),
                jsonpath="$.target.item_id",
            ),
        )
    return HandlerOutcome(result_payload=result, primary_success=True)


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "github.merge_queue.hold",
        "handler": handle_hold,
        "request_model": MergeQueueHoldRequest,
        "response_model": MergeQueueHoldResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.github_merge_queue_hold",
        "target_kinds": ["item"],
        "side_effects": [
            "github:disable_pull_request_auto_merge",
            "github:dequeue_pull_request",
        ],
        "emitted_event_names": [],
        "guardrails": ["project_auth_required"],
        "adapter_status": "live",
        "claim_required_kind": "item",
    },
]


__all__ = [
    "MergeQueueHoldRequest",
    "MergeQueueHoldResponse",
    "REGISTRATIONS",
    "handle_hold",
]
