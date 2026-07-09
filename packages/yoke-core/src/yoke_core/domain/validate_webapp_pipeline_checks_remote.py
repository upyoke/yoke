"""Remote / network-shaped pre-flight checks for the webapp pipeline validator.

Owns Section 3 (GitHub Actions infrastructure), Section 4 (Yoke pipeline
entrypoint presence), Section 5 (deployment flow readiness), and Section 6
(SSH connectivity). GitHub probes route through the App-backed REST
transport (``gh_rest_transport.request_with_retry``). The repo-scoped
GitHub Actions secrets listing (``GET /repos/{o}/{n}/actions/secrets``)
uses the App bearer token resolved for the project and is the only secret
enumeration this validator performs.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from yoke_core.domain import gh_rest_transport
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    repair_command_hint,
    resolve_project_github_auth,
)

from .validate_webapp_pipeline_helpers import (
    Counters,
    ValidateContext,
    _check_fail,
    _check_pass,
    _check_warn,
    _connect,
    _p,
    _query_scalar,
    _resolve_project_identity,
    _run,  # noqa: F401  # retained for test monkeypatch surface compatibility
    _which,  # noqa: F401  # retained for test monkeypatch surface compatibility
)


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _check_github_actions_infrastructure(
    ctx: ValidateContext,
    counters: Counters,
    repo_path: str,
    github_repo: str,
) -> None:
    print("\n=== GitHub Actions Infrastructure ===\n")

    project_key = ctx.project
    project_slug = ctx.project
    project_display = ctx.project_display
    project_upper = ctx.project_upper
    if ctx.control_plane_marker.is_file():
        conn = _connect(ctx.control_plane_marker)
        try:
            try:
                ident = _resolve_project_identity(conn, project_key)
            except LookupError:
                ident = None
            if ident is not None:
                project_slug = ident.slug
                project_display = ident.name or ident.slug.capitalize()
                project_upper = ident.slug.upper()
        finally:
            conn.close()

    # 3a. Canonical project GitHub auth resolves. App-backed REST is the
    # GitHub transport now; the host ``gh`` CLI is NOT a Yoke prerequisite. A
    # typed resolver error names the binding, installation, permission, or
    # credential gap and ``repair_command_hint`` directs operators to the
    # canonical repair. Skip when the control-plane marker is absent;
    # ``_check_database_prerequisites`` already surfaced that as a FAIL.
    token: str = ""
    if ctx.control_plane_marker.is_file():
        try:
            resolved = resolve_project_github_auth(
                project_key, db_path=str(ctx.control_plane_marker),
            )
            token = resolved.token
            _check_pass(
                counters, f"{project_slug} github auth resolved (canonical)"
            )
        except ProjectGithubAuthError as exc:
            _check_fail(
                counters,
                f"{project_slug} github auth not resolvable: {exc}",
                f"Repair: {repair_command_hint(exc, project_slug)}",
            )

    # 3b. Workflow files
    workflows_dir = Path(repo_path) / ".github" / "workflows" if repo_path else None
    if workflows_dir and workflows_dir.is_dir():
        for wf in (f"{project_slug}-deploy.yml", f"{project_slug}-smoke.yml"):
            if (workflows_dir / wf).is_file():
                _check_pass(counters, f"Workflow file exists: {wf}")
            else:
                _check_fail(
                    counters,
                    f"Workflow file missing: {wf}",
                    f"Run bootstrap: python3 -m yoke_core.domain.bootstrap_project cli {project_slug}",
                )
        for wf in (
            f"{project_slug}-ephemeral.yml",
            f"{project_slug}-ephemeral-teardown.yml",
        ):
            if (workflows_dir / wf).is_file():
                _check_pass(counters, f"Workflow file exists: {wf}")
            else:
                _check_warn(counters, f"Optional workflow file missing: {wf}")
    else:
        _check_fail(
            counters,
            f"No .github/workflows directory in {project_display} repo",
            f"Run bootstrap: python3 -m yoke_core.domain.bootstrap_project cli {project_slug}",
        )

    # 3c. GitHub Actions secrets (repo-scoped App permission).
    if token and github_repo:
        secret_names = _rest_actions_secret_names(github_repo, token)
        for sec in (
            f"{project_upper}_SSH_KEY",
            f"{project_upper}_SSH_HOST",
            f"{project_upper}_SSH_USER",
        ):
            if sec in secret_names:
                _check_pass(counters, f"GitHub secret exists: {sec}")
            else:
                _check_fail(
                    counters,
                    f"GitHub secret missing: {sec}",
                    f"Run bootstrap: python3 -m yoke_core.domain.bootstrap_project cli {project_slug}",
                )

    # 3d. Production environment
    if token and github_repo:
        if _rest_environment_exists(github_repo, "production", token):
            _check_pass(counters, "GitHub environment 'production' exists")
        else:
            _check_fail(
                counters,
                "GitHub environment 'production' not found",
                f"Run bootstrap: python3 -m yoke_core.domain.bootstrap_project cli {project_slug}",
            )


def _rest_actions_secret_names(repo: str, token: str) -> list[str]:
    try:
        resp = gh_rest_transport.request_with_retry(
            gh_rest_transport.RestRequest(
                method="GET", path=f"/repos/{repo}/actions/secrets",
            ),
            token=token,
        )
    except gh_rest_transport.RestTransportError:
        return []
    if not isinstance(resp.body, dict):
        return []
    names: list[str] = []
    for entry in resp.body.get("secrets", []) or []:
        if isinstance(entry, dict):
            name = entry.get("name")
            if isinstance(name, str):
                names.append(name)
    return names


def _rest_environment_exists(repo: str, name: str, token: str) -> bool:
    try:
        resp = gh_rest_transport.request_with_retry(
            gh_rest_transport.RestRequest(
                method="GET", path=f"/repos/{repo}/environments",
            ),
            token=token,
        )
    except gh_rest_transport.RestTransportError:
        return False
    if not isinstance(resp.body, dict):
        return False
    for entry in resp.body.get("environments", []) or []:
        if isinstance(entry, dict) and entry.get("name") == name:
            return True
    return False


def _check_pipeline_scripts(_ctx: ValidateContext, counters: Counters) -> None:
    print("\n=== Yoke Pipeline Entrypoints ===\n")

    for module_name in (
        "yoke_core.domain.worktree",
        "yoke_core.engines.merge_worktree",
        "yoke_core.domain.projects",
        "yoke_core.domain.flow",
        "yoke_core.domain.deploy_pipeline",
        "yoke_core.domain.github_actions",
        "yoke_core.tools.executors",
    ):
        if _module_available(module_name):
            _check_pass(counters, f"Python entrypoint exists: {module_name}")
        else:
            _check_fail(counters, f"Python entrypoint missing: {module_name}")


def _check_deployment_flow_readiness(
    ctx: ValidateContext, counters: Counters
) -> None:
    print("\n=== Deployment Flow Readiness ===\n")

    if not ctx.control_plane_marker.is_file():
        flow_id = f"{ctx.project}-prod-release"
        missing_flow = f"{flow_id} flow not found or has no stages"
        _check_fail(counters, missing_flow)
        return

    conn = _connect(ctx.control_plane_marker)
    try:
        try:
            ident = _resolve_project_identity(conn, ctx.project)
        except LookupError:
            ident = None
        if ident is None:
            flow_id = f"{ctx.project}-prod-release"
            stages_raw = None
            missing_flow = f"{flow_id} flow not found or has no stages"
        else:
            flow_id = f"{ident.slug}-prod-release"
            missing_flow = f"{flow_id} flow not found or has no stages"
            stages_raw = _query_scalar(
                conn,
                f"SELECT stages FROM deployment_flows WHERE id={_p(conn)} "
                f"AND project_id={_p(conn)}",
                (flow_id, ident.id),
            )
    finally:
        conn.close()

    if not stages_raw:
        _check_fail(counters, missing_flow)
        return

    try:
        stages = json.loads(stages_raw)
        if not isinstance(stages, list):
            raise ValueError("stages is not a list")
        stage_count = len(stages)
    except (json.JSONDecodeError, ValueError):
        _check_fail(counters, missing_flow)
        return

    _check_pass(counters, f"{flow_id} flow has {stage_count} stage(s)")
    if ctx.verbose:
        for stage in stages:
            if isinstance(stage, dict):
                name = stage.get("name", "?")
                executor = stage.get("executor", "?")
                print(f"       - {name} ({executor})")


def _check_ssh_connectivity(ctx: ValidateContext, counters: Counters) -> None:
    print("\n=== SSH Connectivity (optional) ===\n")

    # Advisory until a dedicated SSH probe owns host/user resolution per
    # project.
    ssh_host = ""
    ssh_user = ""
    _check_warn(
        counters,
        f"SSH config incomplete (host={ssh_host}, user={ssh_user})",
    )
