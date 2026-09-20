"""Stage-specific step runner dispatch for deployment pipeline orchestration."""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Mapping, Optional

from yoke_core.domain import deploy_pipeline_fleet_rehearsal
from yoke_core.domain.deploy_preview_dispatch_boundary import (
    release_preview_identity,
)
from yoke_core.domain.deploy_ephemeral_verify import dispatch_ephemeral_verify
from yoke_core.domain.deploy_health_check import dispatch_health_check
from yoke_core.domain.deploy_pipeline_github_workflow import (
    _dispatch_github_actions_workflow,
)
from yoke_core.domain.deploy_pipeline_events import emit_run_event
from yoke_core.tools import step_runners as _step_runners

__all__ = [
    "_dispatch_step_runner",
    "_dispatch_ephemeral_verify",
    "_dispatch_github_actions_workflow",
    "_dispatch_warm_up",
]


def _dispatch_step_runner(
    stage: Dict[str, Any],
    *,
    run_id: str,
    member_items: List[str],
    github_repo: str,
    project: str,
    project_repo_path: str,
    branch: str,
    first_item: str,
    first_item_label: str = "",
    timeout_min: int,
    fresh: bool,
    image_tag: str = "",
    environment_name: str = "",
    bound_inputs: Optional[Mapping[str, str]] = None,
    gate_branch: str,
    release_lineage: str,
    product_repo_path: str = "",
    sd: Optional[str] = None,
) -> tuple[int, str]:
    """Dispatch the step runner for a stage.

    Returns ``(exit_code, diagnostic)``; diagnostic carries step runner output for
    the pipeline's failure event.
    """
    step_runner = stage["step_runner"]
    config = stage["config"]
    name = stage["name"]

    if step_runner == "auto":
        return _step_runners.exec_auto(), ""
    if step_runner == "health-check":
        return dispatch_health_check(
            config,
            project,
            environment_name,
            project_repo_path=product_repo_path or project_repo_path,
            image_tag=str(config.get("image_tag", "") or image_tag or ""),
            release_lineage=release_lineage,
        )
    if step_runner == "warm-up":
        return _dispatch_warm_up(
            config,
            run_id=run_id,
            member_items=member_items,
            project=project,
            environment_name=environment_name,
        )
    if step_runner == "environment-activate":
        from yoke_core.domain.deploy_environment_activate import (
            exec_environment_activate,
        )

        return exec_environment_activate(project, environment_name), ""
    if step_runner == "core-container-deploy":
        from yoke_core.domain.deploy_core_container import (
            exec_core_container_deploy,
        )

        return (
            exec_core_container_deploy(
                project,
                environment_name,
                repo_path=product_repo_path or project_repo_path,
                image_tag=str(config.get("image_tag", "") or image_tag or ""),
            ),
            "",
        )
    # A stage whose own target is a run preview deploys the run's frozen
    # candidate, named for the release rather than for a branch, whichever
    # path deploys it. A branch preview — every other preview stage — keeps
    # deploying that branch's current head under the branch name, which is
    # what a development preview is for.
    release_preview = str((stage.get("target") or {}).get("kind") or "") == "run_preview"
    # One recorded identity for both deploy paths: the run's own id. The
    # project's own deploy workflow receives exactly this string and
    # publishes it verbatim, so the host Yoke probes is the host that was
    # deployed — deriving either side from the dispatch correlation instead
    # named two different hosts, because that token is per-attempt.
    release_identity = (
        release_preview_identity(stage, run_id=run_id) if release_preview else ""
    )

    if step_runner == "ephemeral-deploy":
        from yoke_core.domain.deploy_ephemeral import exec_ephemeral_deploy

        return (
            exec_ephemeral_deploy(
                project,
                branch=branch or str(config.get("branch", "") or ""),
                repo_path=project_repo_path,
                image_tag=str(config.get("image_tag", "") or ""),
                item_label=first_item_label,
                preview_key=release_identity,
                revision=release_lineage if release_preview else "",
            ),
            "",
        )
    if step_runner == "ephemeral-verify":
        return _dispatch_ephemeral_verify(
            config,
            name=name,
            run_id=run_id,
            member_items=member_items,
            github_repo=github_repo,
            project=project,
            project_repo_path=project_repo_path,
            branch=branch,
            first_item=first_item,
            first_item_label=first_item_label,
            sd=sd,
        )
    if step_runner == "human-approval":
        from yoke_core.domain.deployment_stage_approval_dispatch import (
            dispatch_deployment_stage_approval,
        )

        return dispatch_deployment_stage_approval(run_id, name)
    if step_runner == "qa":
        from yoke_core.domain.deployment_qa_stage_dispatch import (
            dispatch_deployment_qa_stage,
        )

        return dispatch_deployment_qa_stage(stage, run_id=run_id)
    if step_runner == "github-actions-workflow":
        rehearsal_rc, rehearsal_diag = (
            deploy_pipeline_fleet_rehearsal.ensure_before_dispatch(
                config,
                stage_name=name,
                project=project,
                environment=environment_name,
                repository=project_repo_path,
                release_lineage=release_lineage,
            )
        )
        if rehearsal_rc != 0:
            return rehearsal_rc, rehearsal_diag
        return _dispatch_github_actions_workflow(
            config,
            name=name,
            run_id=run_id,
            member_items=member_items,
            github_repo=github_repo,
            project=project,
            project_repo_path=project_repo_path,
            timeout_min=timeout_min,
            fresh=fresh,
            gate_branch=gate_branch,
            sd=sd,
            release_lineage=release_lineage,
            product_repo_path=product_repo_path,
            image_tag=str(config.get("image_tag", "") or image_tag or ""),
            environment_name=environment_name,
            bound_inputs=bound_inputs,
            preview_slug=release_identity,
        )

    print(f"Error: unknown step runner type '{step_runner}'", file=sys.stderr)
    return 1, ""


def _resolve_warm_up_connection(config: Mapping[str, Any], project: str, environment_name: str) -> str:
    declared = str(config.get("connection_env", "") or "").strip()
    if declared:
        return declared
    from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.domain.environment_declared_facts import (
        MissingEnvironmentFact,
        SERVING_CONNECTION_PATH,
        serving_connection_for_environment,
        settings_from_projection,
    )

    name = str(environment_name or "").strip()
    if not name:
        return ""
    try:
        response = call_dispatcher(
            function_id="projects.environment_settings.get",
            target=TargetRef(kind="global"),
            payload={
                "project": project,
                "environment": name,
                "paths": [SERVING_CONNECTION_PATH],
            },
        )
    except Exception as exc:  # noqa: BLE001 - named refusal, not a silent fallback
        raise MissingEnvironmentFact(name, SERVING_CONNECTION_PATH) from exc
    if not response.success:
        raise MissingEnvironmentFact(name, SERVING_CONNECTION_PATH)
    values = response.result.get("values") if isinstance(response.result, Mapping) else {}
    return serving_connection_for_environment(
        name, settings_from_projection(values if isinstance(values, Mapping) else {})
    )


def _dispatch_warm_up(
    config: Dict[str, Any],
    *,
    run_id: str,
    member_items: List[str],
    project: str,
    environment_name: str = "",
) -> tuple[int, str]:
    """Pay the rolled environment's cold start before the run reports success.

    The health probe proves the box is alive; this proves it answers real
    work. A passing call records what was warmed and how long the cold
    start took on the run itself, so the receipt carries the latency the
    pipeline absorbed. A failing call returns the real error, so the stage
    fails with it instead of leaving a cold box marked deployed.
    """
    from yoke_core.domain.deploy_warm_up import (
        DEFAULT_WARM_UP_FUNCTION,
        DEFAULT_WARM_UP_TIMEOUT_S,
        warm_up_environment,
    )
    from yoke_core.domain.environment_declared_facts import MissingEnvironmentFact

    try:
        connection_env = _resolve_warm_up_connection(
            config, project, environment_name
        )
    except MissingEnvironmentFact as exc:
        return 1, str(exc)

    outcome = warm_up_environment(
        connection_env,
        function_id=str(config.get("function", "") or DEFAULT_WARM_UP_FUNCTION),
        timeout_s=float(config.get("timeout_s", 0) or DEFAULT_WARM_UP_TIMEOUT_S),
    )
    print(f"exec-warm-up: {outcome.detail}")
    if not outcome.ok:
        return 1, outcome.detail
    emit_run_event(
        "DeploymentRunWarmedUp",
        "completed",
        {
            "run_id": run_id,
            "connection_env": outcome.connection_env,
            "function": outcome.function_id,
            "latency_ms": outcome.latency_ms,
        },
        member_items=member_items,
        project=project,
    )
    return 0, ""


def _dispatch_ephemeral_verify(
    config: Dict[str, Any],
    *,
    name: str,
    run_id: str,
    member_items: List[str],
    github_repo: str,
    project: str,
    project_repo_path: str,
    branch: str,
    first_item: str,
    first_item_label: str = "",
    sd: Optional[str] = None,
) -> tuple[int, str]:
    """Handle ephemeral-verify step runner. Returns ``(exit_code, preview_url)``."""
    return dispatch_ephemeral_verify(
        config,
        name=name,
        run_id=run_id,
        member_items=member_items,
        github_repo=github_repo,
        project=project,
        branch=branch,
        first_item=first_item,
        first_item_label=first_item_label,
        step_runners=_step_runners,
        sd=sd,
    )
