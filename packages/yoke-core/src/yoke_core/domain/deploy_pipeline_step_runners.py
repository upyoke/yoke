"""Stage-specific step runner dispatch for deployment pipeline orchestration."""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional

from yoke_core.domain.db_helpers import connect, query_scalar
from yoke_core.domain.deploy_ephemeral_verify import dispatch_ephemeral_verify
from yoke_core.domain.deploy_pipeline_labels import item_label as _item_label
from yoke_core.domain.deploy_pipeline_github_workflow import (
    _dispatch_github_actions_workflow,
)
from yoke_core.domain.deploy_cli_manifest_gate import (
    verify_deployed_cli_manifest,
)
from yoke_core.tools import step_runners as _step_runners

__all__ = [
    "_dispatch_step_runner",
    "_dispatch_ephemeral_verify",
    "_dispatch_github_actions_workflow",
]

# Health-check warmup: poll through the container swap window so the gate
# tolerates the brief interval between core-deploy's container-health wait and
# the edge serving the NEW build, without ever passing a stale/failed swap —
# the build assertion still gates every attempt.
HEALTH_CHECK_WARMUP_TIMEOUT_S = 120.0
HEALTH_CHECK_RETRY_INTERVAL_S = 6.0


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
    timeout_min: int,
    fresh: bool,
    image_tag: str = "",
    target_env: str = "",
    gate_branch: str,
    release_lineage: str,
    product_repo_path: str = "",
    sd: Optional[str] = None,
) -> tuple[int, str]:
    """Dispatch the step runner for a stage.

    Returns ``(exit_code, diagnostic)``; diagnostic carries step runner output for
    the pipeline's failure event.

    Kind-typed stages dispatch before the step runner vocabulary:
    ``kind=migration_apply`` routes through the governed-migration
    evidence surface (:mod:`yoke_core.domain.deploy_pipeline_migration`).
    """
    kind = str(stage.get("kind", "") or "")
    if kind == "migration_apply":
        from yoke_core.domain.deploy_pipeline_migration import (
            _dispatch_migration_apply,
        )

        return _dispatch_migration_apply(
            stage,
            run_id=run_id,
            member_items=member_items,
            project=project,
            sd=sd,
        )
    if kind:
        print(f"Error: unknown stage kind '{kind}'", file=sys.stderr)
        return 1, ""

    step_runner = stage["step_runner"]
    config = stage["config"]
    name = stage["name"]

    if step_runner == "auto":
        return _step_runners.exec_auto(), ""
    if step_runner == "health-check":
        return (
            _dispatch_health_check(
                config,
                project,
                target_env,
                project_repo_path=product_repo_path or project_repo_path,
                image_tag=str(config.get("image_tag", "") or image_tag or ""),
            ),
            "",
        )
    if step_runner == "environment-activate":
        from yoke_core.domain.deploy_environment_activate import (
            exec_environment_activate,
        )

        return exec_environment_activate(project, target_env), ""
    if step_runner == "core-container-deploy":
        from yoke_core.domain.deploy_core_container import (
            exec_core_container_deploy,
        )

        return (
            exec_core_container_deploy(
                project,
                target_env,
                repo_path=product_repo_path or project_repo_path,
                image_tag=str(config.get("image_tag", "") or image_tag or ""),
            ),
            "",
        )
    if step_runner == "ephemeral-deploy":
        from yoke_core.domain.deploy_ephemeral import exec_ephemeral_deploy

        return (
            exec_ephemeral_deploy(
                project,
                branch=branch or str(config.get("branch", "") or ""),
                repo_path=project_repo_path,
                image_tag=str(config.get("image_tag", "") or ""),
                item_label=_item_label(first_item),
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
            sd=sd,
        ), ""
    if step_runner == "human-approval":
        from yoke_core.domain.deployment_approval_requests import (
            dispatch_deployment_stage_approval,
        )

        return dispatch_deployment_stage_approval(run_id, name)
    if step_runner == "github-actions-workflow":
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
        )

    print(f"Error: unknown step runner type '{step_runner}'", file=sys.stderr)
    return 1, ""


def _dispatch_health_check(
    config: Dict[str, Any],
    project: str,
    target_env: str,
    *,
    project_repo_path: str = "",
    image_tag: str = "",
) -> int:
    """Run the health-check step runner with env-resolved URL when omitted.

    An explicit ``url`` in the stage config is used verbatim (no request-id
    contract assumed for arbitrary endpoints). Without one, the URL resolves
    from the flow's target environment (``https://{hosts.api}{health_path}``)
    and the check enforces the Yoke core x-request-id echo contract PLUS
    the build assertion: the response's ``build`` must equal the tag this
    pipeline deploys (resolved the same way core-deploy resolves it), so
    the gate proves the NEW code answered — not a stale container that
    survived a failed swap. Without a repo path the expectation cannot be
    resolved and the check states so instead of silently weakening.

    The env-resolved check also requires ``schema_ready: true`` in the
    health payload: HTTP liveness plus the right build still says nothing
    about the DB behind the service, and a core over a schema-incomplete
    DB answers 200 while its data routes fail.
    """
    url = str(config.get("url", "") or "")
    if url:
        return _step_runners.exec_health_check(url)
    if not target_env:
        print(
            "Error: health-check stage has no url and the flow declares no "
            "target_env to resolve one from",
            file=sys.stderr,
        )
        return 1
    from yoke_core.domain.deploy_environment_settings import (
        DeployEnvironmentError,
        resolve_deploy_environment,
    )

    try:
        env = resolve_deploy_environment(project, target_env)
    except DeployEnvironmentError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    import uuid as _uuid

    expected_build = ""
    if image_tag:
        expected_build = image_tag
        print(
            "exec-health-check: build assertion uses explicit deploy image "
            f"tag {expected_build}",
        )
    elif project_repo_path:
        from yoke_core.domain.deploy_core_container_image import (
            resolve_image_tag,
        )
        from yoke_core.domain.deploy_remote import CommandRunner

        try:
            expected_build = resolve_image_tag(
                CommandRunner(),
                project_repo_path,
                "",
                declared_branch=env.git_branch,
            )
        except Exception as exc:
            print(
                "exec-health-check: build assertion skipped — expected tag "
                f"unresolvable from {project_repo_path}: {exc}",
            )
    else:
        print(
            "exec-health-check: build assertion skipped — no project repo "
            "path available to resolve the expected tag",
        )
    rc = _step_runners.exec_health_check(
        env.api_health_url,
        request_id=str(_uuid.uuid4()),
        expected_build=expected_build,
        require_schema_ready=True,
        warmup_timeout=HEALTH_CHECK_WARMUP_TIMEOUT_S,
        retry_interval=HEALTH_CHECK_RETRY_INTERVAL_S,
    )
    if rc != 0:
        return rc
    if env.deploy_namespace == "yoke":
        manifest_gate = verify_deployed_cli_manifest(target_env)
        print(manifest_gate.message)
        if manifest_gate.checked and not manifest_gate.ok:
            return 1
    return 0


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
    sd: Optional[str] = None,
) -> int:
    """Handle ephemeral-verify step runner."""
    return dispatch_ephemeral_verify(
        config,
        name=name,
        run_id=run_id,
        member_items=member_items,
        github_repo=github_repo,
        project=project,
        branch=branch,
        first_item=first_item,
        step_runners=_step_runners,
        connect_fn=connect,
        query_scalar_fn=query_scalar,
        sd=sd,
    )
