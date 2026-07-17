"""Stage-specific executor dispatch for deployment pipeline orchestration."""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from typing import Any, Dict, List, Optional

from yoke_core.domain.db_helpers import connect, query_scalar
from yoke_core.domain.deploy_pipeline_github_workflow import (
    _dispatch_github_actions_workflow,
)
from yoke_core.domain.deploy_pipeline_reporting import (
    _emit_run_event,
    _resolve_script_dir,
)
from yoke_core.domain.deploy_cli_manifest_gate import (
    verify_deployed_cli_manifest,
)
from yoke_core.tools import executors as _executors

__all__ = [
    "_dispatch_executor",
    "_dispatch_ephemeral_verify",
    "_dispatch_github_actions_workflow",
]

# Health-check warmup: poll through the container swap window so the gate
# tolerates the brief interval between core-deploy's container-health wait and
# the edge serving the NEW build, without ever passing a stale/failed swap —
# the build assertion still gates every attempt.
HEALTH_CHECK_WARMUP_TIMEOUT_S = 120.0
HEALTH_CHECK_RETRY_INTERVAL_S = 6.0


def _dispatch_executor(
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
    """Dispatch the executor for a stage.

    Returns ``(exit_code, diagnostic)``; diagnostic carries executor output for
    the pipeline's failure event.

    Kind-typed stages dispatch before the executor vocabulary:
    ``kind=migration_apply`` routes through the governed-migration
    evidence surface (:mod:`yoke_core.domain.deploy_pipeline_migration`).
    """
    kind = str(stage.get("kind", "") or "")
    if kind == "migration_apply":
        from yoke_core.domain.deploy_pipeline_migration import (
            _dispatch_migration_apply,
        )

        return _dispatch_migration_apply(
            stage, run_id=run_id, member_items=member_items,
            project=project, sd=sd,
        )
    if kind:
        print(f"Error: unknown stage kind '{kind}'", file=sys.stderr)
        return 1, ""

    executor = stage["executor"]
    config = stage["config"]
    name = stage["name"]

    if executor == "auto":
        return _executors.exec_auto(), ""
    if executor == "health-check":
        return (
            _dispatch_health_check(
                config, project, target_env,
                project_repo_path=product_repo_path or project_repo_path,
                image_tag=str(config.get("image_tag", "") or image_tag or ""),
            ),
            "",
        )
    if executor == "environment-activate":
        from yoke_core.domain.deploy_environment_activate import (
            exec_environment_activate,
        )

        return exec_environment_activate(project, target_env), ""
    if executor == "core-container-deploy":
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
    if executor == "ephemeral-deploy":
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
    if executor == "ephemeral-verify":
        return _dispatch_ephemeral_verify(
            config, name=name, run_id=run_id, member_items=member_items,
            github_repo=github_repo, project=project,
            project_repo_path=project_repo_path, branch=branch,
            first_item=first_item, sd=sd,
        ), ""
    if executor == "human-approval":
        print(f"Awaiting human approval for stage '{name}'")
        _emit_run_event(
            "DeploymentRunStageCompleted", "completed",
            {"run_id": run_id, "stage": name, "result": "skipped", "reason": "awaiting-approval"},
            member_items=member_items, project=project, sd=sd,
        )
        return -2, ""
    if executor == "github-actions-workflow":
        return _dispatch_github_actions_workflow(
            config, name=name, run_id=run_id, member_items=member_items,
            github_repo=github_repo, project=project,
            project_repo_path=project_repo_path,
            timeout_min=timeout_min, fresh=fresh,
            gate_branch=gate_branch, sd=sd,
            release_lineage=release_lineage,
            product_repo_path=product_repo_path,
            image_tag=str(config.get("image_tag", "") or image_tag or ""),
        )

    print(f"Error: unknown executor type '{executor}'", file=sys.stderr)
    return 1, ""


def _item_label(first_item: str) -> str:
    """Public item ref for ephemeral tracking, or empty for item-less runs."""
    if not first_item:
        return ""
    from yoke_core.domain.project_identity import render_item_ref

    conn = connect()
    try:
        return render_item_ref(conn, int(first_item))
    except Exception:
        return str(first_item)
    finally:
        conn.close()


def _dispatch_health_check(
    config: Dict[str, Any],
    project: str,
    target_env: str,
    *,
    project_repo_path: str = "",
    image_tag: str = "",
) -> int:
    """Run the health-check executor with env-resolved URL when omitted.

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
        return _executors.exec_health_check(url)
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
                CommandRunner(), project_repo_path, "",
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
    rc = _executors.exec_health_check(
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
    """Handle ephemeral-verify executor."""
    sd = sd or _resolve_script_dir()

    all_passed = True
    conn = connect()
    try:
        for item_id in member_items:
            count = query_scalar(
                conn,
                "SELECT COUNT(*) FROM qa_runs qr "
                "JOIN qa_requirements qreq ON qr.qa_requirement_id = qreq.id "
                "WHERE qreq.item_id = %s AND qreq.qa_kind IN ('browser_smoke', 'browser_diff') "
                "AND qreq.qa_phase = 'verification' AND qr.verdict = 'pass'",
                (item_id,),
            )
            if not count:
                all_passed = False
                break
    finally:
        conn.close()

    if all_passed:
        print("  Skipping ephemeral-verify: all member items already passed ephemeral QA during conduct")
        return 0

    workflow = config.get("workflow", "")
    if not github_repo:
        print(f"Error: no github_repo configured for project '{project}'", file=sys.stderr)
        return 1
    if not branch or branch == "null":
        print(f"Error: no branch available for YOK-{first_item} -- cannot verify ephemeral deploy", file=sys.stderr)
        return 1

    from yoke_core.domain.ephemeral_substrate import (
        EphemeralPolicyError,
        load_ephemeral_policy,
    )

    try:
        domain = load_ephemeral_policy(project).preview_domain
    except EphemeralPolicyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if not workflow:
        print("Error: ephemeral-verify stage missing 'workflow' field in flow definition", file=sys.stderr)
        return 1

    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            rc = _executors.exec_ephemeral_verify(
                github_repo, branch, workflow, domain, "", project=project,
            )
    except Exception as exc:  # pragma: no cover
        print(f"Error: exec_ephemeral_verify raised: {exc}", file=sys.stderr)
        return 1

    output = buf.getvalue().strip()
    if output:
        print(output)

    if rc == 0:
        for line in output.split("\n"):
            if line.startswith("EPHEMERAL_URL="):
                _emit_run_event(
                    "DeploymentRunStageCompleted", "completed",
                    {"run_id": run_id, "stage": name, "result": "success", "preview_url": line.split("=", 1)[1]},
                    member_items=member_items, project=project, sd=sd,
                )
                return -3

    return rc
