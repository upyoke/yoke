"""Review readiness at the standalone merge boundary.

`yoke merge item` lands a branch and, unless ``--skip-status`` is passed,
closes the item out afterwards. Both halves used to accept an item still
sitting in implementation: the landing was armed from wherever the item
stood, so a pull request could be armed and a queue entry created for work
the declared review stage had never seen, and the close-out then asked for
a jump straight to the terminal stage.

The status write refuses that jump on its own. It cannot refuse the landing,
because ``--skip-status`` legitimately lands a branch without moving the
item — the item-bound deployment run needs the merge identity before the
close-out. So admission asks the same declared question the status write
asks: has this item reached the stage its own workflow declares for review.

Reaching that stage is what runs the review stage's gates. This check never
records that a review happened; it only refuses to land work that has not
had one.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain import json_helper
from yoke_core.domain.workflow_declared_transitions import unreached_review_stage
from yoke_core.domain.workflow_registry import WorkflowRegistryError
from yoke_core.domain.workflow_runtime import (
    WorkflowRuntime,
    workflow_runtime_from_row,
)


def _pinned_workflow(item: dict[str, Any]) -> tuple[Optional[WorkflowRuntime], str]:
    """Load the definition the item pins. Returns ``(runtime, error)``.

    The pin is asked for exactly as the item names it, so a pin that names
    no workflow or no version fails as a read that could not be answered
    rather than as a second opinion about the payload's shape.
    """
    pin = item.get("workflow") or {}
    named = f"{pin.get('id') or '<unnamed>'}@{pin.get('version')}"
    response = call_dispatcher(
        function_id="workflows.version.get",
        target=TargetRef(kind="global"),
        payload={
            "workflow_id": pin.get("id") or "",
            "version": pin.get("version"),
        },
    )
    if not response.success:
        error = getattr(response, "error", None)
        detail = getattr(error, "message", None) or "workflow version read failed"
        return None, f"{named} could not be read: {detail}"
    result = response.result or {}
    try:
        runtime = workflow_runtime_from_row(
            {
                "workflow_version_id": result["version_id"],
                "workflow_id": result["workflow_id"],
                "version": result["version"],
                "definition_json": json_helper.dumps_compact(result["definition"]),
                "definition_digest": result["definition_digest"],
            }
        )
    except (KeyError, TypeError, ValueError, WorkflowRegistryError) as exc:
        return None, f"{named} could not be interpreted: {exc}"
    return runtime, ""


def review_readiness_refusal(item: dict[str, Any], *, public_ref: str) -> str:
    """Why this item may not be landed yet, or empty when it may.

    Fails closed on a definition it cannot read: a merge boundary that
    cannot ask the question must not answer it with a landing.
    """
    status = str(item.get("status") or "")
    workflow, error = _pinned_workflow(item)
    if workflow is None:
        return (
            f"review readiness could not be checked because {error}. Merge "
            "admission reads the pinned workflow definition; resolve the "
            "control-plane read and re-run this merge."
        )
    review_stage_id = unreached_review_stage(workflow, status)
    if not review_stage_id:
        return ""
    return (
        f"{public_ref} is at {status!r} and "
        f"{workflow.workflow_id}@{workflow.version} declares review at "
        f"{review_stage_id!r}. Landing a branch requires the item to have "
        "reached it, and --skip-status does not waive that. Run `yoke "
        f"lifecycle transition {public_ref} --from {status} --to "
        f'{review_stage_id} --reason "<what was verified>"` — which runs '
        "that stage's own gates — then re-run this merge."
    )


__all__ = ["review_readiness_refusal"]
