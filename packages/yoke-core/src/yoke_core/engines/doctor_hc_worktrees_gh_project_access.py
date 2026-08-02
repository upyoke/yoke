"""Project doctor checks requiring GitHub secrets or VPS access."""

from __future__ import annotations

import json

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_SECRETS_READ_PERMISSION_LEVELS,
)
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.gh_rest_transport import (
    RestAuthError,
    RestNotFoundError,
    RestRequest,
    RestTransportError,
    request_with_retry,
)
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    resolve_project_github_auth,
)
from yoke_core.domain.project_identity import resolve_project_id

import yoke_core.engines.doctor_report as doctor_report

from yoke_core.engines.doctor_hc_gh_skip import GH_APP_AUTH_UNAVAILABLE_SKIP_REASON
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def hc_project_gh_secrets(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """Check whether the verified repository has Actions secrets configured."""
    name_label = f"GitHub Actions secrets ({args.project})"
    slug = "HC-project-gh-secrets"
    if not doctor_report._table_exists(conn, "projects"):
        return
    try:
        auth = resolve_project_github_auth(
            args.project,
            db_path=args.db_path,
            conn=conn,
            required_permissions=GITHUB_SECRETS_READ_PERMISSION_LEVELS,
        )
    except ProjectGithubAuthError:
        rec.record(
            slug,
            name_label,
            "SKIP",
            GH_APP_AUTH_UNAVAILABLE_SKIP_REASON.format(project=args.project),
        )
        return
    gh_repo = auth.repo
    parts = gh_repo.split("/", 1)
    if len(parts) != 2:
        rec.record(slug, name_label, "WARN", f"malformed github_repo '{gh_repo}'")
        return
    owner, name = parts
    try:
        response = request_with_retry(
            RestRequest(method="GET", path=f"/repos/{owner}/{name}/actions/secrets"),
            token=auth.token,
        )
    except RestAuthError:
        rec.record(
            slug,
            name_label,
            "SKIP",
            GH_APP_AUTH_UNAVAILABLE_SKIP_REASON.format(project=args.project),
        )
        return
    except RestNotFoundError:
        rec.record(
            slug,
            name_label,
            "WARN",
            f"Repo {gh_repo} not found via REST (or access denied)",
        )
        return
    except RestTransportError as exc:
        rec.record(
            slug,
            name_label,
            "WARN",
            f"REST error listing secrets in {gh_repo}: {exc}",
        )
        return
    body = response.body if isinstance(response.body, dict) else {}
    count = int(body.get("total_count") or 0)
    rec.record(
        slug,
        name_label,
        "PASS" if count > 0 else "WARN",
        f"{count} secrets configured in {gh_repo}" if count > 0 else f"No secrets found in {gh_repo}",
    )


def hc_project_vps_reachable(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """Check VPS SSH connectivity for projects that declare the capability."""
    if args.project == "yoke" or not doctor_report._table_exists(
        conn, "project_capabilities"
    ):
        return
    project_id = resolve_project_id(conn, args.project)
    rows = query_rows(
        conn,
        "SELECT COALESCE(settings, '{}') FROM project_capabilities WHERE project_id=%s AND type='vps-ssh'",
        (project_id,),
    )
    if not rows:
        return
    try:
        config = json.loads(rows[0][0]) if rows[0][0] else {}
    except (json.JSONDecodeError, TypeError):
        return
    host = config.get("host", "")
    if not host:
        rec.record(
            "HC-project-vps-reachable",
            f"VPS reachable ({args.project})",
            "WARN",
            "vps-ssh capability has no host in config",
        )
        return
    result = doctor_report._run(
        ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", host, "echo ok"],
        timeout=10,
    )
    rec.record(
        "HC-project-vps-reachable",
        f"VPS reachable ({args.project})",
        "PASS" if result.returncode == 0 else "WARN",
        f"SSH to {host} succeeded"
        if result.returncode == 0
        else f"SSH to {host} failed or timed out",
    )
