"""GitHub App repository binding reporting for project onboarding."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_contracts.project_contract.github_sync_mode import (
    GITHUB_SYNC_BACKLOG_ONLY,
)


class ProjectGithubAdoptionError(RuntimeError):
    """Project GitHub adoption cannot proceed."""


GITHUB_ADOPTION_APP_BINDING = "app-binding"
GITHUB_ADOPTION_BACKLOG_ONLY = "backlog-only"
GITHUB_ADOPTION_PRESERVE = "preserve-existing"
GITHUB_ADOPTION_CHOICES = (
    GITHUB_ADOPTION_APP_BINDING,
    GITHUB_ADOPTION_BACKLOG_ONLY,
)
GITHUB_ADOPTION_INPUT_CHOICES = GITHUB_ADOPTION_CHOICES
GITHUB_BINDING_PENDING_STATUS = "pending_app_connection"
GITHUB_BINDING_BACKLOG_ONLY_STATUS = "backlog_only"
GITHUB_BINDING_PRESERVED_STATUS = "preserved"
GITHUB_AUTOMATION_CATEGORIES = (
    "labels",
    "issue_templates",
    "pull_request_templates",
    "actions_variables",
    "actions_secrets",
)
GITHUB_ADMIN_AUTOMATION_CATEGORIES = (
    "branch_protection",
    "environment_protection",
    "runner_administration",
)
PROJECT_SURFACE_BY_OPERATION = {
    "project.create": "projects.create",
    "project.import": "projects.create",
    "project.clone-existing": "projects.get",
    "onboard.project": "project.upsert",
    "onboard.source-dev-admin": "project.upsert",
}


def github_adoption_report(
    *,
    choice: str | None,
    github_repo: str | None,
    apply: bool,
    preserve_existing: bool = False,
) -> dict[str, Any]:
    explicit = choice is not None and not preserve_existing
    normalized = (
        GITHUB_ADOPTION_PRESERVE
        if preserve_existing and choice is None
        else _normalize_github_adoption_choice(
            choice=choice, github_repo=github_repo,
        )
    )
    if not github_repo and normalized == GITHUB_ADOPTION_APP_BINDING:
        raise ProjectGithubAdoptionError(
            "--github-adoption app-binding requires --github-repo OWNER/REPO"
        )
    binding_status = (
        GITHUB_BINDING_PRESERVED_STATUS
        if preserve_existing
        else
        GITHUB_BINDING_PENDING_STATUS
        if normalized == GITHUB_ADOPTION_APP_BINDING
        else GITHUB_BINDING_BACKLOG_ONLY_STATUS
    )

    return {
        "choice": normalized,
        "explicit": explicit,
        "preserve_existing": preserve_existing,
        "github_repo": github_repo,
        "automation_enabled": bool(
            github_repo
            and normalized == GITHUB_ADOPTION_APP_BINDING
            and not preserve_existing
        ),
        "requires_explicit_choice": False,
        "binding": {
            "status": binding_status,
            "repo": github_repo,
            "requires_app_installation": (
                normalized == GITHUB_ADOPTION_APP_BINDING
                and not preserve_existing
            ),
        },
    }


def should_store_project_github_binding(
    github_adoption: Mapping[str, Any] | None,
) -> bool:
    return bool(
        github_adoption
        and not github_adoption.get("preserve_existing")
        and github_adoption.get("choice") == GITHUB_ADOPTION_APP_BINDING
        and github_adoption.get("github_repo")
    )


def github_sync_mode(github_adoption: Mapping[str, Any] | None) -> str:
    """Stage onboarding safely; verified binding enables sync transactionally."""
    return GITHUB_SYNC_BACKLOG_ONLY


def with_github_adoption_report(
    report: dict[str, Any],
    *,
    operation: str,
    root: Path,
    project: Mapping[str, Any],
    github_adoption: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not github_adoption:
        return report
    report["github_adoption"] = dict(github_adoption)
    report["automation_preview"] = automation_preview(
        operation=operation,
        root=root,
        project=project,
        github_adoption=github_adoption,
    )
    return report


def automation_preview(
    *,
    operation: str,
    root: Path,
    project: Mapping[str, Any],
    github_adoption: Mapping[str, Any],
) -> dict[str, Any]:
    github_repo = _project_value(project, "github_repo")
    return {
        "project": {
            "surface": PROJECT_SURFACE_BY_OPERATION.get(operation, operation),
            "checkout": str(root),
            "writes": _project_write_preview(
                operation=operation,
                project=project,
                github_adoption=github_adoption,
            ),
        },
        "github": {
            "repo": github_repo,
            "enabled": bool(github_adoption.get("automation_enabled")),
            "writes": _github_write_preview(
                github_repo=github_repo,
                github_adoption=github_adoption,
            ),
        },
    }


def _normalize_github_adoption_choice(
    *,
    choice: str | None,
    github_repo: str | None,
) -> str:
    if choice is not None:
        if choice not in GITHUB_ADOPTION_CHOICES:
            raise ProjectGithubAdoptionError(
                "unknown GitHub adoption choice: "
                f"{choice}; expected one of app-binding, backlog-only"
            )
        return choice
    if not github_repo:
        return GITHUB_ADOPTION_BACKLOG_ONLY
    return GITHUB_ADOPTION_APP_BINDING


def _project_write_preview(
    *,
    operation: str,
    project: Mapping[str, Any],
    github_adoption: Mapping[str, Any],
) -> list[dict[str, Any]]:
    writes = [{
        "surface": PROJECT_SURFACE_BY_OPERATION.get(operation, operation),
        "fields": sorted(str(key) for key in project.keys()),
    }]
    if (
        github_adoption.get("choice") == GITHUB_ADOPTION_APP_BINDING
        and not github_adoption.get("preserve_existing")
    ):
        writes.append({
            "surface": "project.github_app_repo_binding",
            "repo": _project_value(project, "github_repo"),
            "status": GITHUB_BINDING_PENDING_STATUS,
        })
    writes.extend([
        {"surface": "project.checkout.register", "checkout": "machine-config"},
        {"surface": "project.install", "checkout": "local"},
    ])
    return writes


def _github_write_preview(
    *,
    github_repo: str | None,
    github_adoption: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if github_adoption.get("preserve_existing"):
        status = "preserved-existing"
    elif not github_repo:
        status = "skipped-no-repo"
    elif github_adoption.get("automation_enabled"):
        status = "pending-app-installation"
    else:
        status = "skipped-by-adoption-choice"
    writes = [
        {
            "category": category,
            "target": github_repo,
            "status": status,
            "items": [],
        }
        for category in GITHUB_AUTOMATION_CATEGORIES
    ]
    admin_status = (
        "requires-optional-administration"
        if github_repo and github_adoption.get("automation_enabled")
        else status
    )
    writes.extend({
        "category": category,
        "target": github_repo,
        "status": admin_status,
        "items": [],
    } for category in GITHUB_ADMIN_AUTOMATION_CATEGORIES)
    return writes


def _project_value(project: Mapping[str, Any], key: str) -> Any:
    value = project.get(key)
    if value is not None:
        return value
    if key == "github_repo":
        return project.get("githubRepo")
    return None
