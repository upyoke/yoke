"""Composer: deploy-run setup for a single item, behind one entrypoint.

Resolves the target, then creates the run with the item enrolled and its
composition validated in one transaction
(:func:`~yoke_core.domain.deployment_run_create_write.create_run`). Stops at
validation — deploy execution remains a separate operator call into
``yoke_core.domain.deploy_pipeline``. The composer never invokes
``deploy_pipeline`` directly so the scope boundary holds.

Every failure returns a structured handle rather than raising. A refused
creation writes nothing: no run, no membership, and no takeover of an older
run on the same target. An item a takeover already moved onto the new run is
the membership asked for, not a duplicate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from yoke_core.domain.project_identity_item_ref import item_ref_for_id as _ref
from yoke_core.domain.deployment_run_ci_tested_source import require_tested_lineage
from yoke_core.domain.deployment_run_create_write import (
    CompositionRefused,
    create_run,
)
from yoke_core.domain.deployment_run_target_resolution import (
    EnvironmentRegistryMigrationRequired,
    cmd_resolve_target,
)
from yoke_core.domain.deployment_run_lineage_rebind import (
    PREPARE_NAMES_NO_LINEAGE,
)
from yoke_core.domain.environment_delivery_record import STAGE_ENV_NAME
from yoke_core.domain.deployment_item_flow_resolution import (
    describe_missing_flow as _describe_missing_flow,
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
PHASE_VALIDATE = "validate-composition"


@dataclass
class StartForItemResult:
    """Structured handle returned by :func:`start_for_item`.

    ``ok=True`` means setup succeeded through ``validate-composition``;
    the caller may now invoke ``deploy_pipeline`` with ``run_id``. A failure
    created nothing, so it carries no ``run_id``.
    """

    ok: bool
    project: Optional[str] = None
    flow: Optional[str] = None
    target_tier: Optional[str] = None
    target_environment_id: Optional[int] = None
    target_environment_name: Optional[str] = None
    run_id: Optional[str] = None
    validation_message: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    error_phase: Optional[str] = None
    item_ids: List[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        out = {
            "ok": self.ok,
            "project": self.project,
            "flow": self.flow,
            "target_tier": self.target_tier,
            "target_environment": self.target_environment_name,
            "run_id": self.run_id,
            "item_ids": list(self.item_ids),
        }
        if self.validation_message is not None:
            out["validation_message"] = self.validation_message
        if not self.ok:
            out["error"] = self.error
            if self.error_code is not None:
                out["error_code"] = self.error_code
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
    prepare: bool = False,
    session_id: Optional[str] = None,
) -> StartForItemResult:
    """Compose deploy-run setup for ``item_id`` into one structured call.

    Explicit kwargs override the values pulled from the item row, which
    matches the equivalent hand-rolled five-step sequence.

    ``prepare`` records the run before the work has merged, for a change
    whose consumer must land alongside it: no lineage is bound because the
    commit does not exist yet, and partners still to merge are tolerated.
    Everything else — flow, environment, membership — is
    decided here, and ``continue_for_item`` binds the commit at the merge
    that completes the pair.
    """
    if prepare and release_lineage:
        return StartForItemResult(
            ok=False,
            item_ids=[item_id],
            error=PREPARE_NAMES_NO_LINEAGE,
            error_code="prepare_lineage_conflict",
            error_phase=PHASE_VALIDATE_LINEAGE,
        )
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
            error=f"{_ref(item_id)} has no project; cannot start deploy run",
            error_phase=PHASE_RESOLVE,
        )
    if not resolved_flow:
        return StartForItemResult(
            ok=False,
            project=resolved_project,
            flow=resolved_flow,
            item_ids=[item_id],
            error=_describe_missing_flow(_ref(item_id), resolved_project),
            error_phase=PHASE_RESOLVE,
        )

    try:
        target_tier, target_environment_id, environment_name = cmd_resolve_target(
            resolved_project,
            resolved_flow,
            environment_override=environment,
        )
    except EnvironmentRegistryMigrationRequired as exc:
        return StartForItemResult(
            ok=False,
            project=resolved_project,
            flow=resolved_flow,
            item_ids=[item_id],
            error=str(exc),
            error_code=exc.code,
            error_phase=PHASE_RESOLVE,
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

    if not prepare and not release_lineage and environment_name == STAGE_ENV_NAME:
        try:
            release_lineage, lineage_error = _resolve_remote_release_head(
                resolved_project,
                target_tier,
                environment_name,
                project_repo_path,
            )
        except Exception as exc:
            lineage_error = f"release-lineage binding failed: {exc}"
        if lineage_error == NO_LOCAL_CHECKOUT:
            lineage_error = (
                f"{_ref(item_id)} targets stage but project "
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
                environment_name,
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

    handle = {
        "project": resolved_project,
        "flow": resolved_flow,
        "target_tier": target_tier,
        "target_environment_id": target_environment_id,
        "target_environment_name": environment_name,
        "item_ids": [item_id],
    }
    try:
        require_tested_lineage(
            resolved_project, resolved_flow, environment, release_lineage
        )
        created = create_run(
            resolved_project,
            resolved_flow,
            environment=environment,
            release_lineage=release_lineage,
            created_by=created_by,
            allow_pending_pair_merges=prepare,
            session_id=session_id,
            enroll_item_id=item_id,
        )
    except CompositionRefused as exc:
        return StartForItemResult(
            **handle,
            ok=False,
            validation_message=str(exc),
            error=f"validate-composition failed: {exc}",
            error_phase=PHASE_VALIDATE,
        )
    except Exception as exc:
        return StartForItemResult(
            **handle,
            ok=False,
            error=f"create-run failed: {exc}",
            error_code=getattr(exc, "code", None),
            error_phase=PHASE_CREATE,
        )
    return StartForItemResult(
        **handle,
        ok=True,
        run_id=created.run_id,
        validation_message=created.validation_message,
    )


__all__ = [
    "PHASE_RESOLVE",
    "PHASE_VALIDATE_LINEAGE",
    "PHASE_CREATE",
    "PHASE_VALIDATE",
    "StartForItemResult",
    "start_for_item",
]
