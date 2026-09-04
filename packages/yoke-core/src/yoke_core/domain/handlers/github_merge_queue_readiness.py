"""Registered read of one item's live merge-queue standing."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class MergeQueueReadinessRequest(BaseModel):
    """The item target carries the landing identity."""


class MergeQueueReadinessResponse(BaseModel):
    item_id: int
    public_ref: str
    project: str
    pr_number: str
    target: str
    landing_state: str
    in_flight: Optional[bool]
    queue_holding: str
    queue_entry_state: str
    merge_when_ready: str
    merged: Optional[bool]
    closed: Optional[bool]
    merge_state_status: str
    narrative: str
    warnings: List[str] = Field(default_factory=list)


def _error(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def handle_readiness(request: FunctionCallRequest) -> HandlerOutcome:
    """Read GitHub's PR and target-branch queue facts without mutating either."""
    if request.target.kind != "item" or request.target.item_id is None:
        return _error(
            "target_invalid",
            "github.merge_queue.readiness requires a resolved item target",
            "$.target",
        )

    from yoke_core.domain.item_detail_read import get_item_detail
    from yoke_core.domain.merge_queue_readiness import (
        not_started,
        read_merge_queue_readiness,
    )
    from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext

    try:
        item = get_item_detail(int(request.target.item_id))
    except LookupError as exc:
        return _error("not_found", str(exc), "$.target.item_id")

    project = item.get("project") or {}
    target = str(project.get("default_branch") or "main")
    pr_number = str((item.get("merge_queue") or {}).get("pr_number") or "")
    if pr_number:
        ctx = MergeContext(
            args=MergeArgs(branch="", target=target),
            project=str(project.get("slug") or ""),
        )
        readiness = read_merge_queue_readiness(
            ctx,
            pr_number=pr_number,
            target=target,
        )
    else:
        readiness = not_started(target=target)
    result: Dict[str, Any] = {
        "item_id": int(item["id"]),
        "public_ref": str(item.get("public_ref") or request.target.item_id),
        "project": str(project.get("slug") or ""),
        **readiness.to_dict(),
    }
    return HandlerOutcome(result_payload=result, primary_success=True)


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "github.merge_queue.readiness",
        "handler": handle_readiness,
        "request_model": MergeQueueReadinessRequest,
        "response_model": MergeQueueReadinessResponse,
        "stability": "stable",
        "owner_module": ("yoke_core.domain.handlers.github_merge_queue_readiness"),
        "target_kinds": ["item"],
        "side_effects": [],
        "emitted_event_names": [],
        "guardrails": ["project_auth_required"],
        "adapter_status": "live",
        "claim_required_kind": None,
    },
]


__all__ = [
    "MergeQueueReadinessRequest",
    "MergeQueueReadinessResponse",
    "REGISTRATIONS",
    "handle_readiness",
]
