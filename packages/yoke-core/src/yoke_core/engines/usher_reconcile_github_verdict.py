"""Reconciliation verdict shape and GitHub-poll-to-verdict mapping.

Split out of ``usher_reconcile_github`` so that module stays under the
authored-file line budget; this module owns exactly the outcome shape and
the pure mapping from one GitHub Actions poll result onto it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.deploy_pipeline_events import emit_run_event as _emit_run_event


@dataclass
class ReconcileResult:
    outcome: str
    item_id: int
    deploy_stage: str = ""
    workflow_run_id: str = ""
    gh_status: str = ""
    gh_conclusion: str = ""
    message: str = ""


def error(item_id: int, deploy_stage: str, message: str) -> ReconcileResult:
    return ReconcileResult(
        outcome="error", item_id=item_id, deploy_stage=deploy_stage, message=message
    )


def emit_retroactive_completion(
    *,
    run_id: str,
    stage_name: str,
    workflow_run_id: str,
    member_items: List[str],
    project: str,
) -> None:
    _emit_run_event(
        "DeploymentRunStageCompleted",
        "completed",
        {
            "run_id": run_id,
            "stage": stage_name,
            "result": "success",
            "reconciled": True,
            "workflow_run": workflow_run_id,
            "reason": "usher-reconcile-github",
        },
        member_items=member_items,
        project=project,
    )


def clear_deploy_stage(item_id: int, stage_name: str) -> str:
    # Relay-aware, like every other call in this recovery command: an
    # ordinary HTTPS-connected recovery run has no local database to
    # dispatch against, and the caller's own session/actor identity — not
    # a fabricated actor — is what should attribute this write.
    response = call_dispatcher(
        function_id="items.scalar.update",
        target=TargetRef(kind="item", item_id=item_id),
        payload={"field": "deploy_stage", "value": stage_name},
    )
    if response.success:
        return ""
    return response.error.message if response.error else "items.scalar.update failed"


def reconcile_from_gh_poll(
    gh,
    *,
    item_id: int,
    deploy_stage: str,
    stage_name: str,
    run_id: str,
    workflow_run_id: str,
    project: str,
    public_ref: str,
) -> ReconcileResult:
    """Map one GitHub Actions poll outcome onto a reconciliation verdict."""
    rc, gh_message = gh.returncode, (gh.stdout or "").strip()

    if rc == 0 and gh_message == "success":
        clear_error = clear_deploy_stage(item_id, stage_name)
        if clear_error:
            return error(item_id, deploy_stage, clear_error)
        emit_retroactive_completion(
            run_id=run_id,
            stage_name=stage_name,
            workflow_run_id=workflow_run_id,
            member_items=[str(item_id)],
            project=project,
        )
        return ReconcileResult(
            outcome="aligned",
            item_id=item_id,
            deploy_stage=deploy_stage,
            workflow_run_id=workflow_run_id,
            gh_status="completed",
            gh_conclusion="success",
            message=(
                "Yoke records aligned with GitHub truth. "
                f"Resume usher with: /yoke usher {public_ref} --resume"
            ),
        )
    if rc == 1:
        conclusion = (
            gh_message[len("failed:") :]
            if gh_message.startswith("failed:")
            else gh_message
        )
        return ReconcileResult(
            outcome="gh-failure",
            item_id=item_id,
            deploy_stage=deploy_stage,
            workflow_run_id=workflow_run_id,
            gh_status="completed",
            gh_conclusion=conclusion or "failed",
            message=(
                f"GitHub Actions agrees the deploy failed ({gh_message}) for run "
                f"{workflow_run_id}. Yoke's deploy_stage='{deploy_stage}' is "
                "correct; no reconciliation needed."
            ),
        )
    if rc in (2, 3):
        return ReconcileResult(
            outcome="gh-running",
            item_id=item_id,
            deploy_stage=deploy_stage,
            workflow_run_id=workflow_run_id,
            gh_status=gh_message,
            message=(
                f"GitHub Actions run {workflow_run_id} is still {gh_message}. "
                "Do not retry yet — wait for GH to reach a terminal state."
            ),
        )
    return ReconcileResult(
        outcome="error",
        item_id=item_id,
        deploy_stage=deploy_stage,
        workflow_run_id=workflow_run_id,
        message=(
            f"Unexpected GitHub Actions response (rc={rc}, output='{gh_message}'). "
            "Investigate manually; Yoke state not mutated."
        ),
    )


__all__ = [
    "ReconcileResult",
    "clear_deploy_stage",
    "emit_retroactive_completion",
    "error",
    "reconcile_from_gh_poll",
]
