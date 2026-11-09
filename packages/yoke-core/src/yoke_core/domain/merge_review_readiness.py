"""Review readiness at the standalone merge boundary.

`yoke merge item` lands a branch and, unless ``--skip-status`` is passed,
closes the item out afterwards. Neither half may land work the item's own
workflow has not reviewed: admission asks whether the item has reached the
stage its workflow declares for review.

An item one declared edge before that stage is not refused. The merge
performs that transition itself, after every other landing gate passes and
before the branch lands, with ``--verification`` as the reason. Reaching the
stage runs its own gates, so a gate refusal there stops the merge with the
gate's reason. An item further back is refused with the walk it still owes.

Landing readiness rechecks migration declarations and path coverage locally.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
from pathlib import Path

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.runtime_ports.structured_dispatch import get_structured_dispatch
from yoke_core.domain import json_helper
from yoke_core.domain.public_item_target import public_item_target
from yoke_core.domain.workflow_gate_catalog import (
    GATE_NEW_MIGRATIONS_NEED_DB_CLAIM,
    GATE_PATH_CLAIM_BOUNDARY,
)
from yoke_core.domain.workflow_declared_transitions import (
    declares_transition,
    implementation_review_stage_id,
    unreached_review_stage,
)
from yoke_core.domain.workflow_registry import WorkflowRegistryError
from yoke_core.domain.workflow_runtime import (
    WorkflowRuntime,
    workflow_runtime_from_row,
)

call_dispatcher = get_structured_dispatch().call_dispatcher


def pinned_workflow_for_item(
    item: dict[str, Any],
) -> tuple[Optional[WorkflowRuntime], str]:
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


@dataclass(frozen=True)
class ReviewReadiness:
    """Whether the item may land, and the review entry the merge performs."""

    refusal: str = ""
    source_stage: str = ""
    review_stage: str = ""
    #: The gate ids the pinned review stage runs on entry, in definition order.
    review_gates: tuple[str, ...] = ()

    @property
    def enters_review(self) -> bool:
        return bool(self.review_stage)


def review_readiness(item: dict[str, Any], *, public_ref: str) -> ReviewReadiness:
    """Read the item's review position against its pinned workflow.

    Fails closed on a definition it cannot read: a merge boundary that
    cannot ask the question must not answer it with a landing.
    """
    status = str(item.get("status") or "")
    workflow, error = pinned_workflow_for_item(item)
    if workflow is None:
        return ReviewReadiness(
            refusal=(
                f"review readiness could not be checked because {error}. Merge "
                "admission reads the pinned workflow definition; resolve the "
                "control-plane read and re-run this merge."
            )
        )
    review_stage_id = unreached_review_stage(workflow, status)
    if not review_stage_id:
        reached = implementation_review_stage_id(workflow)
        gates = workflow.gate_ids_for_stage(reached) if reached else ()
        if not reached:
            return ReviewReadiness()
        return ReviewReadiness(review_gates=tuple(dict.fromkeys(
            gate for gate in (*gates, GATE_PATH_CLAIM_BOUNDARY)
            if gate in {GATE_NEW_MIGRATIONS_NEED_DB_CLAIM, GATE_PATH_CLAIM_BOUNDARY}
        )))
    if declares_transition(workflow, status, review_stage_id):
        return ReviewReadiness(
            source_stage=status,
            review_stage=review_stage_id,
            review_gates=tuple(dict.fromkeys((
                *(str(gate["id"]) for gate in workflow.gates_for_stage(review_stage_id)),
                GATE_PATH_CLAIM_BOUNDARY,
            ))),
        )
    return ReviewReadiness(
        refusal=(
            f"{public_ref} is at {status!r} and "
            f"{workflow.workflow_id}@{workflow.version} declares review at "
            f"{review_stage_id!r}, more than one declared edge away. The merge "
            "enters review only from the stage directly before it, and "
            "--skip-status does not waive review. Walk the item's declared "
            f"edges with `yoke lifecycle transition {public_ref} --from "
            f'{status} --to <next stage> --reason "<why>"` until it is one '
            "edge before review, then re-run this merge."
        )
    )


def review_entry_refusal(
    public_ref: str,
    readiness: ReviewReadiness,
    *,
    item: dict[str, Any] | None = None,
    integration_target: str = "main",
) -> str:
    """Ask locally inspectable review gates before the landing."""
    if GATE_NEW_MIGRATIONS_NEED_DB_CLAIM in readiness.review_gates:
        refusal = _migration_entry_refusal(public_ref, item or {}, integration_target)
        if refusal:
            return refusal
    if GATE_PATH_CLAIM_BOUNDARY in readiness.review_gates:
        return _path_entry_refusal(public_ref, item or {})
    return ""


def _path_entry_refusal(public_ref: str, item: dict[str, Any]) -> str:
    from yoke_core.domain.standalone_item_merge_lane import lane_path
    from yoke_core.domain.path_claims_boundary import (
        BoundaryCheckError, BoundaryCheckStatus, boundary_check_for_paths,
    )
    from yoke_core.domain.path_claims_integration_resolver import IntegrationTargetDiverged

    response = call_dispatcher(
        function_id="claims.path.list", target=public_item_target(public_ref), payload={},
    )
    if not response.success:
        detail = getattr(response.error, "message", "path claims read failed")
        return f"Path coverage unavailable: {detail}. Restore the item read and retry the merge."
    claims = [claim for claim in (response.result or {}).get("claims") or []
              if claim.get("state") in {"planned", "blocked", "active"}]
    if not claims:
        return ""
    lane = lane_path(item)
    if not lane or not Path(lane).is_dir():
        return "Path coverage needs the item's lane. Restore its checkout and retry the merge."
    declared = sorted({path for claim in claims for path in claim["declared_paths"]})
    for claim in claims:
        try:
            result = boundary_check_for_paths(
                None, project_id=0, candidate_paths=declared,
                integration_target=claim["integration_target"], repo_path=lane,
            )
        except (BoundaryCheckError, IntegrationTargetDiverged) as exc:
            return f"Path boundary unavailable: {exc}. Repair the lane or integration ref and retry."
        if result.status is BoundaryCheckStatus.CONFLICT:
            paths = ", ".join(result.undeclared_paths or result.uncommitted_paths)
            return (
                f"Path-claim boundary refused claim {claim['id']}: {result.diagnostics}; "
                f"offending paths: {paths}. Before merging, run `yoke claims path widen "
                f"--item {public_ref} --claim-id {claim['id']} --add-paths <paths> "
                '--reason "<why>"`, or revert the uncovered change, then retry the merge.'
            )
    return ""


def _migration_entry_refusal(public_ref: str, item: dict[str, Any], integration_target: str) -> str:
    from yoke_core.domain.standalone_item_merge_lane import lane_path
    from yoke_core.domain.new_migrations_db_claim_gate import missing_claim_errors

    lane = lane_path(item)
    if not lane or not Path(lane).is_dir():
        return ""
    response = call_dispatcher(
        function_id="projects.capability_settings.get",
        target=TargetRef(kind="global"),
        payload={
            "project": (item.get("project") or {}).get("slug"),
            "cap_type": "migration_model",
        },
    )
    if not response.success:
        detail = getattr(
            getattr(response, "error", None), "message", "capability read failed"
        )
        return f"migration_model settings unavailable: {detail}. Resolve the control-plane read and retry."
    if not (response.result or {}).get("settings_json"):
        return ""
    claim = call_dispatcher(
        function_id="items.get.run",
        target=public_item_target(public_ref),
        payload={"fields": ["db_mutation_profile"]},
    )
    if not claim.success:
        detail = getattr(
            getattr(claim, "error", None), "message", "DB claim read failed"
        )
        return f"DB claim unavailable: {detail}. Resolve the item read and retry this merge."
    return "\n".join(
        missing_claim_errors(
            profile=((claim.result or {}).get("fields") or {}).get(
                "db_mutation_profile"
            ),
            settings=(response.result or {}).get("settings_json") or "",
            worktree_path=Path(lane),
            integration_target=integration_target,
            public_ref=public_ref,
        )
    )


def gates_left_to_merge(readiness: ReviewReadiness) -> tuple[str, ...]:
    """The review-entry gates only the merge's own transition evaluates."""
    return tuple(
        gate
        for gate in readiness.review_gates
        if gate not in {GATE_NEW_MIGRATIONS_NEED_DB_CLAIM, GATE_PATH_CLAIM_BOUNDARY}
    )


def enter_review_stage(
    public_ref: str, readiness: ReviewReadiness, *, reason: str
) -> str:
    """Move the item into its review stage. Empty on success, else the refusal.

    The transition runs that stage's own gates on the control plane; their
    refusal is returned whole so the merge stops with the gate's reason.
    """
    from yoke_contracts.runtime_ports.structured_dispatch import get_structured_dispatch
    api = get_structured_dispatch()
    from yoke_core.domain.workflow_level_handoff import record_level_handoff

    response = api.call_dispatcher(
        function_id="lifecycle.transition.execute",
        target=public_item_target(public_ref),
        payload={
            "source_status": readiness.source_stage,
            "target_status": readiness.review_stage,
            "reason": reason or "Verified; merge entered review",
        },
    )
    if response.success:
        record_level_handoff(dict(response.result or {}))
        return ""
    error = getattr(response, "error", None)
    detail = getattr(error, "message", None) or "transition refused"
    return (
        "the merge could not move the item from "
        f"{readiness.source_stage!r} to {readiness.review_stage!r}, so nothing "
        f"landed: {detail}\nResolve that stage gate, then re-run this merge."
    )


__all__ = [
    "ReviewReadiness",
    "enter_review_stage",
    "gates_left_to_merge",
    "pinned_workflow_for_item",
    "review_entry_refusal",
    "review_readiness",
]
