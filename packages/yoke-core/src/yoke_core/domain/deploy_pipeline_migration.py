"""Deploy-pipeline dispatch for kind-typed ``migration_apply`` stages.

A ``{"kind": "migration_apply", "model_name": M, "lifecycle_phase": P}``
stage binds the project's governed migration contract into a deployment
flow.  The governed apply itself (rehearse → lease → backup → live-apply,
with the mandatory operator checkpoint between the two units) runs inside
the ticket lifecycle at the declared ``lifecycle_phase`` — never inside
the deploy pipeline, which executes only after member items have left
that phase (``run_pipeline`` transitions items ``implemented → release``
on start).

At pipeline time this stage therefore verifies, per member item, that the
governed contract completed — by re-running the same evidence gate the
lifecycle enforces at ``implementing → reviewing-implementation``
(:func:`check_implementing_to_reviewing_implementation_gate`: completed
``migration_audit`` rows per declared module, retire decision records,
destructive post-state).  That gate is also the single source of the
"nothing to apply" decision: an item whose ``db_mutation_profile`` is
``{"state": "none"}`` passes trivially.  An item-less run
(environment-level deploy — the normal prod-release case) has zero
declared profiles and passes for the same reason; both pass shapes
pre-emit ``DeploymentRunStageCompleted`` with an explicit stage-result
note (the ``-3`` executor sentinel).

A failing gate fails the stage (the run halts at
``<stage>-failed``); the only path to green is the real governed runner —
the gate's remediation text names it.  No DB mutation happens here.
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional, Tuple

from yoke_core.domain.db_mutation_gate_implementing import (
    check_implementing_to_reviewing_implementation_gate,
)
from yoke_core.domain.deploy_pipeline_reporting import _emit_run_event
from yoke_core.domain.flow_validation import (
    VALID_MIGRATION_APPLY_LIFECYCLE_PHASES,
)

__all__ = ["_dispatch_migration_apply"]


def _dispatch_migration_apply(
    stage: Dict[str, Any],
    *,
    run_id: str,
    member_items: List[str],
    project: str,
    sd: Optional[str] = None,
) -> Tuple[int, str]:
    """Execute a ``kind=migration_apply`` stage.

    Returns ``(exit_code, diagnostic)`` per the ``_dispatch_executor``
    contract: ``-3`` = success with the stage-completion event already
    emitted (carrying the explicit stage-result note); ``1`` = the
    governed-migration evidence gate failed for at least one member item
    (``diagnostic`` carries the per-item gate errors for the
    ``DeploymentRunStageFailed`` payload).
    """
    config = stage["config"]
    name = stage["name"]
    model_name = str(config.get("model_name", "") or "")
    lifecycle_phase = str(config.get("lifecycle_phase", "") or "")

    if not model_name:
        diag = (
            f"stage '{name}' (kind=migration_apply) is missing required "
            f"field 'model_name'"
        )
        print(f"Error: {diag}", file=sys.stderr)
        return 1, diag
    if lifecycle_phase not in VALID_MIGRATION_APPLY_LIFECYCLE_PHASES:
        diag = (
            f"stage '{name}' (kind=migration_apply) lifecycle_phase "
            f"'{lifecycle_phase}' is not wired for pipeline dispatch "
            f"(supported: "
            f"{', '.join(sorted(VALID_MIGRATION_APPLY_LIFECYCLE_PHASES))})"
        )
        print(f"Error: {diag}", file=sys.stderr)
        return 1, diag

    if member_items:
        errors: List[str] = []
        for raw_item in member_items:
            item_id = int(str(raw_item).strip().upper().removeprefix("YOK-"))
            outcome = check_implementing_to_reviewing_implementation_gate(
                item_id
            )
            if not outcome.passed:
                errors.extend(
                    f"YOK-{item_id}: {err}" for err in outcome.errors
                )
        if errors:
            for line in errors:
                print(f"  {line}", file=sys.stderr)
            return 1, "\n".join(errors)
        items_verified = len(member_items)
        note = (
            f"governed-migration evidence verified for {items_verified} "
            f"member item(s) (model '{model_name}', lifecycle_phase "
            f"'{lifecycle_phase}'); items with no declared db claim pass "
            f"the gate trivially"
        )
    else:
        items_verified = 0
        note = (
            f"no member items, so no db_mutation_profile declares pending "
            f"modules for model '{model_name}'; the governed apply runs in "
            f"the item lifecycle ({lifecycle_phase}) — nothing to apply at "
            f"deploy time"
        )

    print(f"  {note}")
    _emit_run_event(
        "DeploymentRunStageCompleted", "completed",
        {
            "run_id": run_id,
            "stage": name,
            "result": "success",
            "model_name": model_name,
            "lifecycle_phase": lifecycle_phase,
            "items_verified": items_verified,
            "note": note,
        },
        member_items=member_items, project=project, sd=sd,
    )
    return -3, ""
