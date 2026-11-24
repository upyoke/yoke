"""Read public item lane records on the command's control-plane connection."""

from __future__ import annotations

from typing import Any

from yoke_contracts.api.function_call import ActorContext, TargetRef
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_contracts.runtime_ports.structured_dispatch import get_structured_dispatch

from yoke_core.domain.lane_head_record import reconcile_lane_head
from yoke_core.domain.standalone_item_merge_lane import active_lanes


class LaneHeadClientError(RuntimeError):
    """A selected lane cannot supply a current candidate."""


def read_item_lanes(
    target: TargetRef, *, actor: ActorContext | None = None
) -> tuple[str, list[dict[str, Any]]]:
    response = get_structured_dispatch().call_dispatcher(
        function_id="items.detail.get", target=target, payload={}, actor=actor
    )
    if not response.success:
        detail = response.error.message if response.error else "no item details returned"
        raise LaneHeadClientError(
            compose_refusal(
                f"lane_context_unavailable: {detail}", recovery="rerun the same command"
            )
        )
    item = (response.result or {}).get("item") or {}
    return str((item.get("project") or {}).get("slug") or ""), active_lanes(item)


def reconcile_task_lane(target: TargetRef, *, session_id: str | None = None) -> None:
    dispatch = get_structured_dispatch()
    actor = dispatch.build_actor(session_id=session_id)
    task = dispatch.call_dispatcher(
        function_id="workflow_item.epic_task.get", target=target, payload={}, actor=actor
    )
    if not task.success:
        detail = task.error.message if task.error else "no task record returned"
        raise LaneHeadClientError(
            compose_refusal(
                f"task_review_lane_invalid: {detail}", recovery="rerun review-insert"
            )
        )
    lane_id = (task.result or {}).get("worktree_id")
    if lane_id is None:
        # Older servers omit the structured lane ID; their review write
        # still validates the supplied commit against the durable candidate.
        return
    project, lanes = read_item_lanes(
        TargetRef(kind="item", public_ref=target.public_ref, project_id=target.project_id),
        actor=actor,
    )
    lane = next((row for row in lanes if row.get("id") == lane_id), None)
    if lane is None or lane.get("lane_role") != "worker":
        return
    _, error = reconcile_lane_head(project, lane, session_id=session_id)
    if error:
        raise LaneHeadClientError(error)


def reconcile_done_lane(
    target: TargetRef, *, source_status: str | None = None, session_id: str | None = None
) -> None:
    """Refresh the done gate's selected checkout before sending the transition."""
    dispatch = get_structured_dispatch()
    actor = dispatch.build_actor(session_id=session_id)
    response = dispatch.call_dispatcher(
        function_id="done_transition.item_context", target=target, payload={}, actor=actor
    )
    if not response.success:
        detail = response.error.message if response.error else "no done context returned"
        raise LaneHeadClientError(
            compose_refusal(
                f"lane_context_unavailable: {detail}", recovery="rerun the same command"
            )
        )
    context = response.result or {}
    lane = context.get("lane")
    current = context.get("stage_id")
    if not lane or current == "done" or (source_status and source_status != current):
        return
    _, error = reconcile_lane_head(
        str(context.get("project") or ""), lane, session_id=actor.session_id
    )
    if error:
        raise LaneHeadClientError(error)
