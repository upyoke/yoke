"""Validate deployment-run membership against current item workflow pins."""

from __future__ import annotations

from typing import Any, Iterable

from yoke_core.domain.deployment_run_project_sources import carried_project_ids
from yoke_core.domain.workflow_definition_builders import (
    WORKFLOW_DELIVERY_CONTINUOUS_SLICE_THEN_RELEASE,
)
from yoke_core.domain.workflow_item_binding_validation import (
    PinnedItem,
    WorkflowItemBindingError,
    has_workflow_pin_schema,
    binding_runtime_state,
    read_pinned_items,
)
from yoke_core.domain.workflow_runtime import WorkflowRuntime
from yoke_core.domain.project_identity import render_item_ref


COMPLETED_ITEM_STAGE_ID = "done"


def delivery_ready_for_stage(runtime: WorkflowRuntime, status: str) -> bool:
    position = runtime.stage_index(status)
    if position is None:
        return False
    policy = str(runtime.policies["delivery"])
    if policy == "release_stage":
        starts = [
            runtime.stage_index(str(binding["from_stage_id"]))
            for binding in runtime.definition["skill_bindings"]
            if str(binding["through_stage_id"]) in runtime.terminal_stage_ids
        ]
        valid = [value for value in starts if value is not None]
        if not valid or position < min(valid):
            return False
        # A binding that runs from filing to done (Dash) makes every stage
        # "after its start", so the start alone would call an item back in
        # rework deliverable. Inside an implementation segment only the
        # release wait itself has landed code to ship.
        return runtime.stage_implies_merge(status) or not (
            runtime.implementation_has_started(status)
        )
    if policy in (
        "continuous_slice_actions",
        WORKFLOW_DELIVERY_CONTINUOUS_SLICE_THEN_RELEASE,
    ):
        return runtime.implementation_has_started(status)
    if policy == "after_merge_action":
        return position >= len(runtime.stage_ids) - 2
    return False


def _validate_member_state(
    conn: Any,
    *,
    run_id: str,
    item_id: int,
    pinned: PinnedItem,
    state: tuple[WorkflowRuntime, str],
    allow_completed: bool,
) -> None:
    runtime, status = state
    # Membership follows the code, not the run's own project row: a run that
    # binds another project's source ships that project's merges too, and the
    # items inside them are delivered by this run or by nothing.
    try:
        carried = carried_project_ids(conn, run_id)
    except LookupError as exc:
        raise WorkflowItemBindingError(f"deployment run {run_id!r} not found") from exc
    if pinned.project_id not in carried:
        raise WorkflowItemBindingError(
            f"{render_item_ref(conn, item_id)} belongs to a project deployment "
            f"run {run_id} ships no source for; the run records a source commit "
            "only for its own project and the projects its flow stages bind "
            "through input_bindings"
        )
    if allow_completed and status == COMPLETED_ITEM_STAGE_ID:
        return
    if not delivery_ready_for_stage(runtime, status):
        raise WorkflowItemBindingError(
            f"{render_item_ref(conn, item_id)} workflow {runtime.workflow_id}@{runtime.version} "
            f"is not delivery-ready at stage {status!r}"
        )


def attached_binding_runtime_state(
    conn: Any, item_id: int, pinned: PinnedItem | None
) -> tuple[WorkflowRuntime, str]:
    """An established run member's state, including later completion.

    New bindings reject every terminal item. An item that was admitted while
    delivery-ready may reach its workflow's successful ``done`` stage before
    its run starts; that completion preserves the established membership.
    Engine terminal states such as ``cancelled`` and ``stopped`` remain
    refusals.
    """
    try:
        return binding_runtime_state(conn, item_id, pinned)
    except WorkflowItemBindingError:
        if (
            pinned is None
            or pinned.runtime is None
            or pinned.status != COMPLETED_ITEM_STAGE_ID
            or pinned.status not in pinned.runtime.terminal_stage_ids
        ):
            raise
        return pinned.runtime, pinned.status


def attached_item_binding_runtime_state(
    conn: Any,
    item_id: int,
) -> tuple[WorkflowRuntime, str] | None:
    """Load one established run member's state; see :func:`attached_binding_runtime_state`."""
    if not has_workflow_pin_schema(conn):
        return None
    pinned = read_pinned_items(conn, (int(item_id),)).get(int(item_id))
    return attached_binding_runtime_state(conn, int(item_id), pinned)


def validate_run_member(
    conn: Any,
    *,
    run_id: str,
    item_id: int,
    pinned: PinnedItem | None,
    attached: bool,
) -> tuple[WorkflowRuntime, str]:
    """Require project and delivery-stage compatibility for one member.

    ``attached=False`` validates new admission; ``True`` revalidates
    established membership without re-admitting completed work. Returns the
    member's binding state.
    """
    read_state = attached_binding_runtime_state if attached else binding_runtime_state
    state = read_state(conn, item_id, pinned)
    _validate_member_state(
        conn,
        run_id=run_id,
        item_id=item_id,
        pinned=pinned,
        state=state,
        allow_completed=attached,
    )
    return state


def validate_deployment_run_members(
    conn: Any, *, run_id: str, item_ids: Iterable[int], attached: bool
) -> None:
    """Validate a set of members from one read; the first refusal, in id order, stands."""
    if not has_workflow_pin_schema(conn):
        return
    ids = sorted({int(value) for value in item_ids})
    pinned = read_pinned_items(conn, ids)
    for item_id in ids:
        validate_run_member(
            conn,
            run_id=run_id,
            item_id=item_id,
            pinned=pinned.get(item_id),
            attached=attached,
        )


__all__ = [
    "COMPLETED_ITEM_STAGE_ID",
    "attached_binding_runtime_state",
    "attached_item_binding_runtime_state",
    "delivery_ready_for_stage",
    "validate_deployment_run_members",
    "validate_run_member",
]
