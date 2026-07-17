"""Composer: deploy-run setup for a single item, behind one entrypoint.

Wraps the four existing primitives operators were running by hand:

    runs resolve-target-env  ->  runs create-run  ->  runs add-item
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

import re
from dataclasses import dataclass, field
from typing import List, Optional

from yoke_core.domain.deployment_runs_crud_mutate import (
    cmd_add_item,
    cmd_create_run,
)
from yoke_core.domain.deployment_runs_preview import cmd_resolve_target_env
from yoke_core.domain.deployment_runs_validation import cmd_validate_composition


# Phase identifiers for the structured handle.
PHASE_RESOLVE = "resolve-target-env"
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
    target_env: Optional[str] = None
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
            "target_env": self.target_env,
            "run_id": self.run_id,
            "item_ids": list(self.item_ids),
        }
        if self.validation_message is not None:
            out["validation_message"] = self.validation_message
        if not self.ok:
            out["error"] = self.error
            out["error_phase"] = self.error_phase
        return out


def _lookup_item_project_and_flow(item_id: int) -> tuple:
    """Return (project, deployment_flow) for ``item_id`` from Postgres authority."""
    from yoke_core.domain import db_helpers

    conn = db_helpers.connect()
    try:
        row = conn.execute(
            "SELECT p.slug AS project, i.deployment_flow FROM items i "
            "LEFT JOIN projects p ON p.id = i.project_id WHERE i.id = %s",
            (item_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None, None
    return row[0], row[1]


def _resolve_remote_release_head(
    project: str,
    target_env: str,
) -> tuple[str, str]:
    """Read the current flow gate-branch commit from the project remote."""
    from yoke_core.domain.deploy_pipeline_gates import resolve_flow_gate_branch
    from yoke_core.domain.deploy_pipeline_github_workflow import (
        _resolve_publish_sha,
    )
    from yoke_core.domain.project_checkout_locations import (
        checkout_for_project,
    )
    from yoke_core.domain import db_helpers

    conn = db_helpers.connect()
    try:
        checkout = checkout_for_project(conn, project)
    finally:
        conn.close()
    if checkout is None:
        return "", (
            f"project '{project}' has no checkout for release-lineage validation"
        )

    repo_path = str(checkout)
    gate_branch = resolve_flow_gate_branch(project, target_env, repo_path)
    if not gate_branch:
        return "", (
            "deployment flow has no remote gate branch for commit-lineage "
            "validation"
        )
    remote_sha, error = _resolve_publish_sha(repo_path, gate_branch)
    if error:
        return "", error
    return remote_sha, ""


def _validate_commit_release_lineage(
    project: str,
    target_env: str,
    release_lineage: str,
) -> str:
    """Require an explicit commit lineage to equal the remote release head."""
    if not re.fullmatch(r"[0-9a-f]{40}", release_lineage):
        return ""
    remote_sha, error = _resolve_remote_release_head(project, target_env)
    if error:
        return error
    if release_lineage != remote_sha:
        return (
            f"release_lineage {release_lineage} does not equal the exact "
            f"remote gate-branch commit {remote_sha}"
        )
    return ""


def start_for_item(
    item_id: int,
    *,
    project: Optional[str] = None,
    flow: Optional[str] = None,
    target_env: Optional[str] = None,
    release_lineage: Optional[str] = None,
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
        resolved_target_env = cmd_resolve_target_env(
            resolved_project,
            resolved_flow,
            target_env_override=target_env,
        )
    except Exception as exc:
        return StartForItemResult(
            ok=False,
            project=resolved_project,
            flow=resolved_flow,
            item_ids=[item_id],
            error=f"resolve-target-env failed: {exc}",
            error_phase=PHASE_RESOLVE,
        )

    if not release_lineage and resolved_target_env == "stage":
        try:
            release_lineage, lineage_error = _resolve_remote_release_head(
                resolved_project,
                resolved_target_env,
            )
        except Exception as exc:
            lineage_error = f"release-lineage binding failed: {exc}"
        if lineage_error:
            return StartForItemResult(
                ok=False,
                project=resolved_project,
                flow=resolved_flow,
                target_env=resolved_target_env,
                item_ids=[item_id],
                error=lineage_error,
                error_phase=PHASE_VALIDATE_LINEAGE,
            )
    elif release_lineage:
        try:
            lineage_error = _validate_commit_release_lineage(
                resolved_project,
                resolved_target_env,
                release_lineage,
            )
        except Exception as exc:
            lineage_error = f"release-lineage validation failed: {exc}"
        if lineage_error:
            return StartForItemResult(
                ok=False,
                project=resolved_project,
                flow=resolved_flow,
                target_env=resolved_target_env,
                item_ids=[item_id],
                error=lineage_error,
                error_phase=PHASE_VALIDATE_LINEAGE,
            )

    try:
        run_id = cmd_create_run(
            resolved_project,
            resolved_flow,
            target_env=resolved_target_env,
            release_lineage=release_lineage,
            created_by=created_by,
        )
    except Exception as exc:
        return StartForItemResult(
            ok=False,
            project=resolved_project,
            flow=resolved_flow,
            target_env=resolved_target_env,
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
            target_env=resolved_target_env,
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
            target_env=resolved_target_env,
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
            target_env=resolved_target_env,
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
        target_env=resolved_target_env,
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
