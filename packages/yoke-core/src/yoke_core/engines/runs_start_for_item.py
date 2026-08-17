"""Composer: deploy-run setup for a single item, behind one entrypoint.

Wraps the four existing primitives operators were running by hand:

    runs resolve-target  ->  runs create-run  ->  runs add-item
    ->  runs validate-composition

into one call that returns a structured handle. Stops at validation —
deploy execution remains a separate operator call into
``yoke_core.domain.deploy_pipeline``. The composer never invokes
``deploy_pipeline`` directly so the scope boundary holds.

Failure paths are safe:

* Missing ``project`` / ``deployment_flow`` on the item returns a
  structured error before any DB write.
* A failed ``create-run`` returns immediately; nothing to clean up.
* A failed ``add-item`` or ``validate-composition`` returns the diagnostic
  payload AND the ``run_id`` already created so the operator can inspect
  or clean up via existing ``runs`` commands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from yoke_core.domain.deployment_runs_crud_mutate import (
    cmd_add_item,
    cmd_create_run,
)
from yoke_core.domain.deployment_run_target_resolution import (
    cmd_resolve_target,
)
from yoke_core.domain.deployment_runs_validation import cmd_validate_composition
from yoke_core.domain.environment_delivery_record import STAGE_ENV_NAME
from yoke_core.domain.deployment_item_flow_resolution import (
    lookup_item_project_and_flow as _lookup_item_project_and_flow,
)
from yoke_core.engines.runs_release_lineage import (
    NO_LOCAL_CHECKOUT,
    _resolve_remote_release_head,
    _validate_commit_release_lineage,
)


# Phase identifiers for the structured handle.
PHASE_RESOLVE = "resolve-target"
PHASE_VALIDATE_LINEAGE = "validate-release-lineage"
PHASE_CREATE = "create-run"
PHASE_ADD_ITEM = "add-item"
PHASE_VALIDATE = "validate-composition"


@dataclass
class StartForItemResult:
    """Structured handle returned by :func:`start_for_item`.

    ``ok=True`` means setup succeeded through ``validate-composition``;
    the caller may now invoke ``deploy_pipeline`` with ``run_id``. On
    failure, ``run_id`` may be populated when the failure occurred AFTER
    the run was created — the operator inspects it via existing ``runs``
    commands.
    """

    ok: bool
    project: Optional[str] = None
    flow: Optional[str] = None
    target_tier: Optional[str] = None
    target_environment_id: Optional[str] = None
    target_environment_name: Optional[str] = None
    run_id: Optional[str] = None
    validation_message: Optional[str] = None
    error: Optional[str] = None
    error_phase: Optional[str] = None
    item_ids: List[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        out = {
            "ok": self.ok,
            "project": self.project,
            "flow": self.flow,
            "target_tier": self.target_tier,
            "target_environment_id": self.target_environment_id,
            "target_environment_name": self.target_environment_name,
            "run_id": self.run_id,
            "item_ids": list(self.item_ids),
        }
        if self.validation_message is not None:
            out["validation_message"] = self.validation_message
        if not self.ok:
            out["error"] = self.error
            out["error_phase"] = self.error_phase
        return out


def start_for_item(
    item_id: int,
    *,
    project: Optional[str] = None,
    flow: Optional[str] = None,
    environment: Optional[str] = None,
    release_lineage: Optional[str] = None,
    project_repo_path: str = "",
    created_by: str = "operator",
) -> StartForItemResult:
    """Compose deploy-run setup for ``item_id`` into one structured call.

    Explicit kwargs override the values pulled from the item row, which
    matches the equivalent hand-rolled five-step sequence.
    """
    db_project = db_flow = None
    if project is None or flow is None:
        db_project, db_flow = _lookup_item_project_and_flow(item_id)
    resolved_project = project if project is not None else db_project
    resolved_flow = flow if flow is not None else db_flow

    if not resolved_project:
        return StartForItemResult(
            ok=False,
            project=resolved_project,
            flow=resolved_flow,
            item_ids=[item_id],
            error=f"item {item_id} has no project; cannot start deploy run",
            error_phase=PHASE_RESOLVE,
        )
    if not resolved_flow:
        return StartForItemResult(
            ok=False,
            project=resolved_project,
            flow=resolved_flow,
            item_ids=[item_id],
            error=(
                f"item {item_id} has no deployment_flow; "
                "cannot start deploy run"
            ),
            error_phase=PHASE_RESOLVE,
        )

    try:
        target_tier, target_environment_id, environment_name = (
            cmd_resolve_target(
                resolved_project,
                resolved_flow,
                environment_override=environment,
            )
        )
    except Exception as exc:
        return StartForItemResult(
            ok=False,
            project=resolved_project,
            flow=resolved_flow,
            item_ids=[item_id],
            error=f"resolve-target failed: {exc}",
            error_phase=PHASE_RESOLVE,
        )

    if not release_lineage and environment_name == STAGE_ENV_NAME:
        try:
            release_lineage, lineage_error = _resolve_remote_release_head(
                resolved_project,
                target_tier,
                target_environment_id,
                project_repo_path,
            )
        except Exception as exc:
            lineage_error = f"release-lineage binding failed: {exc}"
        if lineage_error == NO_LOCAL_CHECKOUT:
            lineage_error = (
                f"item {item_id} targets stage but project "
                f"'{resolved_project}' has no machine-local checkout to bind a "
                "release lineage; pass --release-lineage explicitly"
            )
        if lineage_error:
            return StartForItemResult(
                ok=False,
                project=resolved_project,
                flow=resolved_flow,
                target_tier=target_tier,
                target_environment_id=target_environment_id,
                target_environment_name=environment_name,
                item_ids=[item_id],
                error=lineage_error,
                error_phase=PHASE_VALIDATE_LINEAGE,
            )
    elif release_lineage:
        try:
            lineage_error = _validate_commit_release_lineage(
                resolved_project,
                target_tier,
                target_environment_id,
                release_lineage,
                project_repo_path,
            )
        except Exception as exc:
            lineage_error = f"release-lineage validation failed: {exc}"
        if lineage_error:
            return StartForItemResult(
                ok=False,
                project=resolved_project,
                flow=resolved_flow,
                target_tier=target_tier,
                target_environment_id=target_environment_id,
                target_environment_name=environment_name,
                item_ids=[item_id],
                error=lineage_error,
                error_phase=PHASE_VALIDATE_LINEAGE,
            )

    try:
        run_id = cmd_create_run(
            resolved_project,
            resolved_flow,
            environment=environment,
            release_lineage=release_lineage,
            created_by=created_by,
        )
    except Exception as exc:
        return StartForItemResult(
            ok=False,
            project=resolved_project,
            flow=resolved_flow,
            target_tier=target_tier,
            target_environment_id=target_environment_id,
            target_environment_name=environment_name,
            item_ids=[item_id],
            error=f"create-run failed: {exc}",
            error_phase=PHASE_CREATE,
        )

    try:
        cmd_add_item(run_id, item_id)
    except Exception as exc:
        return StartForItemResult(
            ok=False,
            project=resolved_project,
            flow=resolved_flow,
            target_tier=target_tier,
            target_environment_id=target_environment_id,
            target_environment_name=environment_name,
            run_id=run_id,
            item_ids=[item_id],
            error=f"add-item failed: {exc}",
            error_phase=PHASE_ADD_ITEM,
        )

    try:
        ok, msg = cmd_validate_composition(run_id)
    except Exception as exc:
        return StartForItemResult(
            ok=False,
            project=resolved_project,
            flow=resolved_flow,
            target_tier=target_tier,
            target_environment_id=target_environment_id,
            target_environment_name=environment_name,
            run_id=run_id,
            item_ids=[item_id],
            error=f"validate-composition raised: {exc}",
            error_phase=PHASE_VALIDATE,
        )

    if not ok:
        return StartForItemResult(
            ok=False,
            project=resolved_project,
            flow=resolved_flow,
            target_tier=target_tier,
            target_environment_id=target_environment_id,
            target_environment_name=environment_name,
            run_id=run_id,
            item_ids=[item_id],
            validation_message=msg,
            error=f"validate-composition failed: {msg}",
            error_phase=PHASE_VALIDATE,
        )

    return StartForItemResult(
        ok=True,
        project=resolved_project,
        flow=resolved_flow,
        target_tier=target_tier,
        target_environment_id=target_environment_id,
        target_environment_name=environment_name,
        run_id=run_id,
        item_ids=[item_id],
        validation_message=msg,
    )


__all__ = [
    "PHASE_RESOLVE",
    "PHASE_VALIDATE_LINEAGE",
    "PHASE_CREATE",
    "PHASE_ADD_ITEM",
    "PHASE_VALIDATE",
    "StartForItemResult",
    "start_for_item",
]
