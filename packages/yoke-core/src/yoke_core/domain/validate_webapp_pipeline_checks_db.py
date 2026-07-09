"""DB / filesystem-shaped pre-flight checks for the webapp pipeline validator.

Owns Section 1 (Database Prerequisites) and Section 2 (Local Repository).
Both functions consume helpers via bareword imports so that tests can
monkeypatch ``_run`` / ``_which`` on this module's namespace dict — see
``validate_webapp_pipeline_helpers`` for the shared surface.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.project_checkout_locations import checkout_for_project_id

from .validate_webapp_pipeline_helpers import (
    Counters,
    ValidateContext,
    _capability_secret,
    _capability_settings,
    _check_fail,
    _check_pass,
    _check_warn,
    _connect,
    _p,
    _query_scalar,
    _resolve_project_identity,
    _run,
    _table_exists,
)


def _check_database_prerequisites(
    ctx: ValidateContext, counters: Counters
) -> tuple[str, str]:
    """Run Section 1 checks.

    Returns the resolved local ``(checkout_path, github_repo)`` for
    ``ctx.project`` so later sections can reuse them.
    """
    print("\n=== Database Prerequisites ===\n")

    project_key = ctx.project
    project_display = ctx.project_display

    # 1a. Control-plane availability gate. Yoke authority is Postgres; the
    # project / capability / flow rows below are read from the DSN-pointed
    # control plane via ``_connect``, not from this marker. The marker exists
    # for legacy CLI wiring and PG-portable tests; it is not a SQLite authority.
    if ctx.control_plane_marker.is_file():
        _check_pass(
            counters,
            f"control-plane marker exists at {ctx.control_plane_marker}",
        )
    else:
        _check_fail(
            counters,
            f"control-plane marker not found at {ctx.control_plane_marker}",
        )
        _check_fail(
            counters,
            f"{project_display} project not found in projects table",
            f"Register the project: yoke projects create --slug {project_key} "
            f"--name {project_display!r} --github-repo OWNER/REPO "
            "(or onboard via yoke project install)",
        )
        _check_fail(
            counters, f"{project_display} github_repo not set in projects table"
        )
        _check_fail(
            counters,
            f"No github capability for {project_key} in project_capabilities",
        )
        _check_fail(
            counters,
            f"No deployment flows for {project_key}",
            f"Check deployment_flows table has {project_key}-prod-release, "
            f"{project_key}-internal, {project_key}-prod-hotfix",
        )
        _check_warn(
            counters,
            f"No SSH capability for {project_key} (needed for deployment)",
        )
        _check_warn(counters, f"No docker capability for {project_key}")
        return "", ""

    conn = _connect(ctx.control_plane_marker)
    try:
        try:
            ident = _resolve_project_identity(conn, project_key)
        except LookupError:
            _check_fail(
                counters,
                f"{project_display} project not found in projects table",
                f"Register the project: yoke projects create --slug {project_key} "
                f"--name {project_display!r} --github-repo OWNER/REPO "
                "(or onboard via yoke project install)",
            )
            _check_fail(
                counters,
                f"{project_display} github_repo not set in projects table",
            )
            _check_fail(
                counters,
                f"No github capability for {project_key} in project_capabilities",
            )
            _check_fail(
                counters,
                f"No deployment flows for {project_key}",
                f"Check deployment_flows table has {project_key}-prod-release, "
                f"{project_key}-internal, {project_key}-prod-hotfix",
            )
            _check_warn(
                counters,
                f"No SSH capability for {project_key} (needed for deployment)",
            )
            _check_warn(counters, f"No docker capability for {project_key}")
            return "", ""
        project_id = ident.id
        project_slug = ident.slug
        project_display = ident.name or ident.slug.capitalize()
        # 1b. Project record
        checkout = checkout_for_project_id(project_id)
        repo_path = str(checkout) if checkout is not None else ""
        _check_pass(counters, f"{project_display} project record exists")

        # 1c. github_repo field
        github_repo = _query_scalar(
            conn,
            f"SELECT github_repo FROM projects WHERE id={_p(conn)}",
            (project_id,),
        ) or ""
        if github_repo:
            _check_pass(
                counters, f"{project_display} github_repo set: {github_repo}"
            )
        else:
            _check_fail(
                counters,
                f"{project_display} github_repo not set in projects table",
            )

        # 1d. GitHub App binding and control-plane credentials
        github_settings = _capability_settings(conn, project_key, "github")
        if github_settings:
            app_private_key_name = str(
                github_settings.get("private_key_secret_key") or "app_private_key"
            )
            if _table_exists(conn, "project_github_repo_bindings"):
                binding_count_raw = _query_scalar(
                    conn,
                    "SELECT COUNT(*) FROM project_github_repo_bindings "
                    f"WHERE project_id={_p(conn)}",
                    (project_id,),
                )
            else:
                binding_count_raw = "0"
            try:
                binding_count = int(binding_count_raw or 0)
            except (TypeError, ValueError):
                binding_count = 0
            app_private_key = _capability_secret(
                conn, project_key, "github", app_private_key_name,
            )
            if binding_count > 0:
                _check_pass(counters, "GitHub App repo binding configured")
            else:
                _check_fail(
                    counters,
                    "GitHub App repo binding not configured",
                    "Bind via: yoke projects github-binding bind "
                    f"--project {project_slug} ...",
                )
            if app_private_key:
                _check_pass(counters, "GitHub App private key configured")
            else:
                _check_fail(
                    counters,
                    "GitHub App private key not configured",
                    "Store via: yoke projects capability secret set "
                    f"--project {project_slug} --cap-type github "
                    f"--key {app_private_key_name} --value-stdin",
                )
        else:
            _check_fail(
                counters,
                f"No github capability for {project_slug} in project_capabilities",
            )

        # 1e. Deployment flows
        flow_count_raw = _query_scalar(
            conn,
            f"SELECT COUNT(*) FROM deployment_flows WHERE project_id={_p(conn)}",
            (project_id,),
        )
        try:
            flow_count = int(flow_count_raw or 0)
        except (TypeError, ValueError):
            flow_count = 0
        if flow_count >= 1:
            _check_pass(
                counters,
                f"{project_display} deployment flows configured ({flow_count} flow(s))",
            )
            if ctx.verbose:
                for row in conn.execute(
                    f"SELECT id, name FROM deployment_flows WHERE project_id={_p(conn)}",
                    (project_id,),
                ).fetchall():
                    print(f"       - {row['id']} ({row['name']})")
        else:
            _check_fail(
                counters,
                f"No deployment flows for {project_slug}",
                f"Check deployment_flows table has {project_slug}-prod-release, "
                f"{project_slug}-internal, {project_slug}-prod-hotfix",
            )

        # 1f. SSH capability
        ssh_settings = _capability_settings(conn, project_key, "ssh")
        if ssh_settings:
            _check_pass(counters, f"SSH capability configured for {project_slug}")
        else:
            _check_warn(
                counters,
                f"No SSH capability for {project_slug} (needed for deployment)",
            )

        # 1g. Docker capability
        docker_settings = _capability_settings(conn, project_key, "docker")
        if docker_settings:
            _check_pass(counters, f"Docker capability configured for {project_slug}")
        else:
            _check_warn(counters, f"No docker capability for {project_slug}")
    finally:
        conn.close()

    return repo_path, github_repo


def _check_local_repository(
    ctx: ValidateContext,
    counters: Counters,
    repo_path: str,
) -> None:
    print("\n=== Local Repository ===\n")

    project_key = ctx.project
    project_display = ctx.project_display

    repo = Path(repo_path) if repo_path else None

    # 2a. Repo exists
    if repo and (repo / ".git").is_dir():
        _check_pass(counters, f"{project_display} repo exists at {repo_path}")
    else:
        _check_fail(
            counters,
            f"{project_display} repo not found at {repo_path}",
            "Clone the repo and register the checkout in ~/.yoke/config.json",
        )
        return

    # 2b. Clean working tree
    dirty_result = _run(
        ["git", "-C", str(repo), "status", "--porcelain"]
    )
    dirty = dirty_result.stdout if dirty_result.returncode == 0 else ""
    if not dirty:
        _check_pass(counters, f"{project_display} repo working tree is clean")
    else:
        _check_warn(
            counters,
            f"{project_display} repo has uncommitted changes",
            "Consider committing or stashing before running the pipeline",
        )

    # 2c. Default branch
    branch_result = _run(["git", "-C", str(repo), "branch", "--show-current"])
    current_branch = branch_result.stdout.strip() if branch_result.returncode == 0 else ""

    default_branch = "main"
    if ctx.control_plane_marker.is_file():
        conn = _connect(ctx.control_plane_marker)
        try:
            ident = _resolve_project_identity(conn, project_key)
            project_display = ident.name or ident.slug.capitalize()
            default_branch = (
                _query_scalar(
                    conn,
                    f"SELECT default_branch FROM projects WHERE id={_p(conn)}",
                    (ident.id,),
                )
                or "main"
            )
        finally:
            conn.close()
        if not default_branch:
            default_branch = "main"

    if current_branch == default_branch:
        _check_pass(
            counters, f"{project_display} repo on default branch ({default_branch})"
        )
    else:
        _check_warn(
            counters,
            f"{project_display} repo on branch '{current_branch}', expected '{default_branch}'",
        )
