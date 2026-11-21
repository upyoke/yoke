"""Load pinned workflow and item context through the connected transport."""

from __future__ import annotations

from yoke_core.domain import done_transition_item_context
from yoke_core.domain.public_item_target import public_item_target
from yoke_core.domain.workflow_runtime import WorkflowRuntime


def load_done_item_context_over_transport(
    item_id: int,
) -> done_transition_item_context.DoneItemContext | None:
    """Load the done-transition item context through the connected transport.

    Relays ``done_transition.item_context`` so the item + pinned-workflow
    read runs over an https control plane as well as a local Postgres
    connection, then rebuilds the exact :class:`~yoke_core.domain.done_transition_item_context.DoneItemContext` (including a
    fully reconstructed :class:`WorkflowRuntime`) the runner consumes.

    Returns ``None`` for a missing item — the runner's "item not found"
    branch. A read failure (transport unavailable, or an incomplete workflow
    pin surfaced by the handler) raises, aborting the transition exactly as
    the inline ``connect()`` + ``load_done_item_context`` did on a DB-level
    failure.
    """
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )

    resp = call_dispatcher(
        function_id="done_transition.item_context",
        target=public_item_target(item_id),
        payload={},
    )
    if not resp.success:
        message = resp.error.message if resp.error else "unknown error"
        raise RuntimeError(f"done item context read failed: {message}")
    data = resp.result or {}
    if not data.get("found"):
        return None
    return done_transition_item_context.done_item_context_from_payload(data)


def format_workflow_route(runtime: WorkflowRuntime) -> str:
    """Render the ordered route with its terminal stage highlighted."""
    return " -> ".join(
        f"[{stage_id}]" if stage_id == runtime.stage_ids[-1] else stage_id
        for stage_id in runtime.stage_ids
    )
