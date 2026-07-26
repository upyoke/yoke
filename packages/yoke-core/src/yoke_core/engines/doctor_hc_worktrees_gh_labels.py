"""Health check for workflow-labeled GitHub issues without backlog links."""

from __future__ import annotations

from typing import List

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_READ_PERMISSION_LEVELS,
)
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    repair_command_hint,
    resolve_project_github_auth,
)
from yoke_core.domain.projects_github_sync_mode import (
    github_sync_disabled_notice,
    github_sync_enabled,
)
import yoke_core.engines.doctor_hc_worktrees as _wt
import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_hc_gh_skip import (
    GH_APP_AUTH_UNAVAILABLE_SKIP_REASON,
)
from yoke_core.engines.doctor_hc_worktrees_gh_rest import (
    list_issues_by_labels_rest,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def hc_orphaned_gh_issues(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """Find workflow-labeled repository issues not linked to backlog items."""
    if not _wt._github_auth_configured("yoke", db_path=args.db_path):
        rec.record(
            "HC-orphaned-gh-issues", "Orphaned GitHub issues", "SKIP",
            GH_APP_AUTH_UNAVAILABLE_SKIP_REASON.format(project="yoke"),
        )
        return

    known_nums = {
        str(row["github_issue"]).replace("#", "")
        for row in query_rows(
            conn,
            "SELECT github_issue FROM items "
            "WHERE github_issue IS NOT NULL AND github_issue <> ''",
        )
        if row["github_issue"] and row["github_issue"] != "null"
    }
    workflow_labels = [
        f"workflow:{row['id']}"
        for row in query_rows(
            conn, "SELECT id FROM workflows WHERE status = 'active' ORDER BY id",
        )
    ]
    all_issues: set[str] = set()
    auth_failures: List[str] = []
    sync_disabled_notes: List[str] = []

    if _base._table_exists(conn, "projects"):
        projects = query_rows(
            conn,
            "SELECT slug, COALESCE(github_repo, '') as github_repo FROM projects "
            "WHERE github_repo IS NOT NULL AND github_repo <> ''",
        )
        for row in projects:
            project = row["slug"]
            if not github_sync_enabled(project, conn=conn):
                sync_disabled_notes.append(
                    "- " + github_sync_disabled_notice(
                        project, "orphaned-issue scan",
                    )
                )
                continue
            try:
                auth = resolve_project_github_auth(
                    project, db_path=args.db_path,
                    required_permissions=GITHUB_ISSUES_READ_PERMISSION_LEVELS,
                )
            except ProjectGithubAuthError as err:
                auth_failures.append(
                    f"- project '{project}': {err}\n"
                    f"  Repair: {repair_command_hint(err, project)}"
                )
                continue
            parts = auth.repo.split("/", 1)
            if len(parts) != 2:
                continue
            owner, name = parts
            for label in workflow_labels:
                result = list_issues_by_labels_rest(
                    owner=owner, name=name, token=auth.token,
                    labels=[label], state="open",
                )
                if result.returncode == 0:
                    all_issues.update(
                        value.strip() for value in result.stdout.splitlines()
                        if value.strip()
                    )

    if auth_failures:
        rec.record(
            "HC-orphaned-gh-issues", "Orphaned GitHub issues", "FAIL",
            "Cannot resolve project GitHub auth:\n" + "\n".join(auth_failures),
        )
        return

    issues = [
        f"- GitHub issue #{num} has Yoke labels but no matching backlog item"
        for num in sorted(
            all_issues, key=lambda value: int(value) if value.isdigit() else 0,
        )
        if num not in known_nums
    ]
    if issues:
        rec.record(
            "HC-orphaned-gh-issues", "Orphaned GitHub issues", "WARN",
            "\n".join(issues + sync_disabled_notes),
        )
    else:
        rec.record(
            "HC-orphaned-gh-issues", "Orphaned GitHub issues", "PASS",
            "\n".join(sync_disabled_notes),
        )


__all__ = ["hc_orphaned_gh_issues"]
