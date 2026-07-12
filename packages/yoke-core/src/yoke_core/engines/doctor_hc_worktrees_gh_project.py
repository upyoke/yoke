"""Worktree health checks — project-level capability checks.

Project-scoped HCs (repo presence, GitHub App auth, worktrees, deployment
flows, production health, GitHub Actions secrets, VPS reachability).
HC-project-gh-secrets uses bearer-token REST ``GET /actions/secrets``,
which needs ``secrets:read`` (or ``admin:repo``) scope; 401/403 SKIPs
with the canonical reason -- same UX as missing GitHub App auth.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_SECRETS_READ_PERMISSION_LEVELS,
)
from yoke_core.domain.db_helpers import query_rows, query_scalar
from yoke_core.domain.gh_rest_transport import (
    RestAuthError,
    RestNotFoundError,
    RestRequest,
    RestTransportError,
    request_with_retry,
)
from yoke_core.domain.project_github_auth import (
    MissingCapability,
    ProjectGithubAuthError,
    repair_command_hint,
    resolve_project_github_auth,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.project_checkout_locations import checkout_for_project
from yoke_core.domain.projects_github_sync_mode import (
    GithubSyncModeError,
    github_sync_disabled_notice,
    github_sync_enabled,
)

import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_hc_gh_skip import GH_APP_AUTH_UNAVAILABLE_SKIP_REASON
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)

def hc_project_lookup(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-project-lookup: Project lookup."""
    if not _base._table_exists(conn, "projects"):
        rec.record("HC-project-lookup", "Project lookup", "WARN",
                    f"projects table does not exist, cannot look up '{args.project}'")
        return
    exists = query_scalar(conn, "SELECT count(*) FROM projects WHERE slug=%s", (args.project,))
    if not exists or int(exists) == 0:
        rec.record("HC-project-lookup", "Project lookup", "WARN",
                    f"Project '{args.project}' not found in projects table. Skipping project-specific checks.")
    # If found, no record needed (project-specific checks will run)

def hc_project_repo_exists(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-project-repo-exists: Verify project repo exists on disk."""
    if not _base._table_exists(conn, "projects"):
        return
    rp = checkout_for_project(conn, args.project)
    if rp is None:
        rec.record(
            "HC-project-repo-exists",
            f"Project checkout installed ({args.project})",
            "WARN",
            "no machine-local checkout mapping",
        )
        return
    if Path(rp).is_dir():
        rec.record("HC-project-repo-exists", f"Project checkout installed ({args.project})", "PASS", "")
    else:
        rec.record("HC-project-repo-exists", f"Project checkout installed ({args.project})", "FAIL",
                    f"mapped checkout '{rp}' does not exist on disk")

def hc_project_gh_auth(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-project-gh-auth: GitHub App auth for project.

    Resolves through the canonical :func:`resolve_project_github_auth`
    surface; on any typed ``ProjectGithubAuthError`` the HC FAILs with the
    matching :func:`repair_command_hint` so the operator gets a concrete
    fix command in the doctor report.  Fail-closed: no host-credential
    fallback.
    """
    proj_id = args.project
    try:
        resolve_project_github_auth(proj_id, db_path=args.db_path)
    except ProjectGithubAuthError as err:
        intentional_backlog_only = False
        if isinstance(err, MissingCapability):
            try:
                intentional_backlog_only = not github_sync_enabled(
                    proj_id, conn=conn,
                )
            except GithubSyncModeError:
                # Preserve the auth failure when the project policy itself is
                # corrupt; Doctor must not call that an intentional skip.
                pass
        if intentional_backlog_only:
            rec.record(
                "HC-project-gh-auth",
                f"GitHub App auth ({proj_id})",
                "SKIP",
                github_sync_disabled_notice(proj_id, "project auth check"),
            )
            return
        rec.record(
            "HC-project-gh-auth",
            f"GitHub App auth ({proj_id})",
            "FAIL",
            f"{err}\nRepair: {repair_command_hint(err, proj_id)}",
        )
        return

    rec.record(
        "HC-project-gh-auth",
        f"GitHub App auth ({proj_id})",
        "PASS",
        "Resolved GitHub App auth via project repo binding",
    )

def hc_project_worktrees(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-project-worktrees: Project worktree health."""
    if not _base._table_exists(conn, "projects"):
        return
    checkout = checkout_for_project(conn, args.project)
    if checkout is None:
        rec.record(
            "HC-project-worktrees",
            f"Project worktree health ({args.project})",
            "WARN",
            "no machine-local checkout mapping",
        )
        return
    rp = str(checkout)
    if not Path(rp).is_dir():
        rec.record("HC-project-worktrees", f"Project worktree health ({args.project})", "WARN",
                    f"mapped checkout '{rp}' not found")
        return

    r = _base._run(["git", "-C", rp, "worktree", "list", "--porcelain"], timeout=10)
    stale: List[str] = []
    for line in r.stdout.splitlines():
        if line.startswith("worktree "):
            wt_path = line[9:]
            if not Path(wt_path).is_dir():
                stale.append(f"- {wt_path} (missing on disk)")

    if stale:
        rec.record("HC-project-worktrees", f"Project worktree health ({args.project})", "WARN",
                    "Stale worktrees:\n" + "\n".join(stale))
    else:
        rec.record("HC-project-worktrees", f"Project worktree health ({args.project})", "PASS", "")

def hc_project_deploy_flows(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-project-deploy-flows: Deployment flow state for project."""
    if not _base._table_exists(conn, "deployment_flows"):
        return
    project_id = resolve_project_id(conn, args.project)
    rows = query_rows(
        conn,
        "SELECT id, stages FROM deployment_flows WHERE project_id=%s ORDER BY id",
        (project_id,),
    )
    if rows:
        detail = f"{len(rows)} deployment flow(s) for {args.project}"
        rec.record("HC-project-deploy-flows", f"Deployment flow state ({args.project})", "PASS", detail)
    else:
        rec.record("HC-project-deploy-flows", f"Deployment flow state ({args.project})", "PASS",
                    "No deployment flows")

def hc_project_health(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-project-health: Production health check endpoint."""
    if args.project == "yoke":
        # Yoke has no health-endpoint capability; intentionally skipped.
        return
    if not _base._table_exists(conn, "project_capabilities"):
        return

    project_id = resolve_project_id(conn, args.project)
    row = query_rows(
        conn,
        "SELECT COALESCE(settings, '{}') FROM project_capabilities WHERE project_id=%s AND type='health-endpoint'",
        (project_id,),
    )
    if not row:
        return  # No capability = no check

    config_str = row[0][0]
    if not config_str:
        return
    try:
        cfg = json.loads(config_str)
    except (json.JSONDecodeError, TypeError):
        rec.record("HC-project-health", f"Production health ({args.project})", "WARN",
                    "health-endpoint capability has invalid JSON config")
        return

    url = cfg.get("url", "")
    if not url:
        rec.record("HC-project-health", f"Production health ({args.project})", "WARN",
                    "health-endpoint capability has no url in config")
        return

    r = _base._run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
              "--connect-timeout", "5", "--max-time", "10", url], timeout=15)
    status = r.stdout.strip() if r.returncode == 0 else "000"
    if status == "200":
        rec.record("HC-project-health", f"Production health ({args.project})", "PASS",
                    f"{url} returned 200")
    else:
        rec.record("HC-project-health", f"Production health ({args.project})", "WARN",
                    f"{url} returned HTTP {status}")

def hc_project_gh_secrets(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-project-gh-secrets: GitHub Actions secrets present (bearer-token REST).

    ``GET /repos/{owner}/{name}/actions/secrets`` requires the GitHub App auth to
    carry the ``secrets:read`` (or ``admin:repo``) scope; 401/403 SKIPs
    with the canonical reason -- same UX as missing GitHub App auth.
    """
    name_label = f"GitHub Actions secrets ({args.project})"
    slug = "HC-project-gh-secrets"
    if not _base._table_exists(conn, "projects"):
        return
    try:
        auth = resolve_project_github_auth(
            args.project,
            db_path=args.db_path,
            conn=conn,
            required_permissions=GITHUB_SECRETS_READ_PERMISSION_LEVELS,
        )
    except ProjectGithubAuthError:
        rec.record(slug, name_label, "SKIP",
                   GH_APP_AUTH_UNAVAILABLE_SKIP_REASON.format(project=args.project))
        return
    gh_repo = auth.repo
    parts = gh_repo.split("/", 1)
    if len(parts) != 2:
        rec.record(slug, name_label, "WARN", f"malformed github_repo '{gh_repo}'")
        return
    owner, name = parts
    try:
        resp = request_with_retry(
            RestRequest(method="GET", path=f"/repos/{owner}/{name}/actions/secrets"),
            token=auth.token,
        )
    except RestAuthError:
        rec.record(slug, name_label, "SKIP",
                   GH_APP_AUTH_UNAVAILABLE_SKIP_REASON.format(project=args.project))
        return
    except RestNotFoundError:
        rec.record(slug, name_label, "WARN",
                   f"Repo {gh_repo} not found via REST (or access denied)")
        return
    except RestTransportError as exc:
        rec.record(slug, name_label, "WARN",
                   f"REST error listing secrets in {gh_repo}: {exc}")
        return
    body = resp.body if isinstance(resp.body, dict) else {}
    count = int(body.get("total_count") or 0)
    if count > 0:
        rec.record(slug, name_label, "PASS", f"{count} secrets configured in {gh_repo}")
    else:
        rec.record(slug, name_label, "WARN", f"No secrets found in {gh_repo}")

def hc_project_vps_reachable(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-project-vps-reachable: VPS SSH connectivity."""
    if args.project == "yoke":
        # Yoke has no VPS; intentionally skipped.
        return
    if not _base._table_exists(conn, "project_capabilities"):
        return

    project_id = resolve_project_id(conn, args.project)
    row = query_rows(
        conn,
        "SELECT COALESCE(settings, '{}') FROM project_capabilities WHERE project_id=%s AND type='vps-ssh'",
        (project_id,),
    )
    if not row:
        return  # No capability = no check

    config_str = row[0][0]
    if not config_str:
        return
    try:
        cfg = json.loads(config_str)
    except (json.JSONDecodeError, TypeError):
        return

    host = cfg.get("host", "")
    if not host:
        rec.record("HC-project-vps-reachable", f"VPS reachable ({args.project})", "WARN",
                    "vps-ssh capability has no host in config")
        return

    r = _base._run(["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", host, "echo ok"],
             timeout=10)
    if r.returncode == 0:
        rec.record("HC-project-vps-reachable", f"VPS reachable ({args.project})", "PASS",
                    f"SSH to {host} succeeded")
    else:
        rec.record("HC-project-vps-reachable", f"VPS reachable ({args.project})", "WARN",
                    f"SSH to {host} failed or timed out")
