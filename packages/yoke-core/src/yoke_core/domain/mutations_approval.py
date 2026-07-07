"""Deployment approval mutation semantics."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from .approval import FlowStage, resolve_approval
from .mutation_fields import ApprovalResult, ItemState, MutationEvent, MutationEventKind
from .runs import DeploymentRun

def prepare_approval(
    *,
    item: ItemState,
    flow_stages: Sequence[FlowStage],
    active_run: Optional[DeploymentRun],
    member_item_ids: Sequence[int],
) -> ApprovalResult:
    """Validate and prepare an approval-apply mutation.

    Delegates approval-resolution to the domain approval module and
    returns structured information for the adapter to apply.

    Args:
        item: Current item state.
        flow_stages: Parsed flow stages from deployment_flows.stages.
        active_run: The active deployment run for this item (or None).
        member_item_ids: All item IDs in the active run (for dual-write).

    Returns:
        ApprovalResult with next_stage, run_id, member_item_ids on
        success, or error details on failure.
    """
    deploy_stage = item.deploy_stage
    deployment_flow = item.deployment_flow

    if not deploy_stage:
        return ApprovalResult(
            success=False,
            error=f"Item YOK-{item.id} has no deploy_stage set. Cannot approve.",
            error_code="INVALID_STATE",
            item_id=item.id,
        )

    if not deployment_flow:
        return ApprovalResult(
            success=False,
            error=f"Item YOK-{item.id} has no deployment_flow set. Cannot approve.",
            error_code="INVALID_STATE",
            item_id=item.id,
        )

    # Resolve approval via domain layer
    resolution = resolve_approval(flow_stages, deploy_stage)

    if not resolution.approved:
        return ApprovalResult(
            success=False,
            error=(
                f"Item YOK-{item.id} deploy_stage '{deploy_stage}': "
                f"{resolution.error}"
            ),
            error_code="INVALID_STATE",
            item_id=item.id,
        )

    next_stage = resolution.next_stage
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = active_run.id if active_run else None

    events: List[MutationEvent] = [
        MutationEvent(
            kind=MutationEventKind.APPROVAL_APPLIED,
            detail={
                "deploy_stage": deploy_stage,
                "next_stage": next_stage,
                "run_id": run_id,
            },
        ),
    ]

    # Field writes for the run (adapter applies these)
    field_writes: Dict[str, Any] = {}

    if run_id:
        events.append(MutationEvent(
            kind=MutationEventKind.RUN_STAGE_ADVANCED,
            detail={"run_id": run_id, "next_stage": next_stage},
        ))
        # All member items get stage synced
        if member_item_ids:
            events.append(MutationEvent(
                kind=MutationEventKind.MEMBER_STAGE_SYNCED,
                detail={
                    "member_item_ids": list(member_item_ids),
                    "next_stage": next_stage,
                },
            ))

    # Item-level writes: deploy_stage + ensure release status
    field_writes["deploy_stage"] = next_stage
    field_writes["status"] = "release"
    field_writes["updated_at"] = now

    return ApprovalResult(
        success=True,
        next_stage=next_stage,
        run_id=run_id,
        member_item_ids=tuple(member_item_ids),
        approved_at=now,
        field_writes=field_writes,
        events=tuple(events),
        item_id=item.id,
    )
