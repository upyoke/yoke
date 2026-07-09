"""GitHub App repository binding reporting for project onboarding."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


class ProjectGithubAdoptionError(RuntimeError):
    """Project GitHub adoption cannot proceed."""


GITHUB_ADOPTION_APP_BINDING = "app-binding"
GITHUB_ADOPTION_BACKLOG_ONLY = "backlog-only"
GITHUB_ADOPTION_CHOICES = (
    GITHUB_ADOPTION_APP_BINDING,
    GITHUB_ADOPTION_BACKLOG_ONLY,
    "skip",
)
GITHUB_ADOPTION_LEGACY_CHOICES = (
    "temporary-only",
    "store-token",
    "different-token",
)
GITHUB_ADOPTION_INPUT_CHOICES = (
    *GITHUB_ADOPTION_CHOICES,
    *GITHUB_ADOPTION_LEGACY_CHOICES,
)
GITHUB_ADOPTION_STORE_CHOICES: tuple[str, ...] = ()
GITHUB_BINDING_PENDING_STATUS = "pending_app_connection"
GITHUB_BINDING_BACKLOG_ONLY_STATUS = "backlog_only"
GITHUB_AUTOMATION_CATEGORIES = (
    "labels",
    "issue_templates",
    "pull_request_templates",
    "actions_variables",
    "actions_secrets",
    "branch_protection",
    "environment_protection",
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
    token_value: str | None,
    token_import_method: str | None,
    apply: bool,
) -> dict[str, Any]:
    explicit = choice is not None
    if token_value:
        raise ProjectGithubAdoptionError(
            "Project-supplied GitHub credentials are no longer supported. Use "
            "--github-adoption app-binding for a GitHub App repo binding, or "
            "--github-adoption backlog-only."
        )
    normalized = _normalize_github_adoption_choice(
        choice=choice, github_repo=github_repo, token_value=token_value,
    )
    if not github_repo and normalized == GITHUB_ADOPTION_APP_BINDING:
        raise ProjectGithubAdoptionError(
            "--github-adoption app-binding requires --github-repo OWNER/REPO"
        )
    secret: dict[str, Any] = {
        "provided": False,
        "import_method": token_import_method,
        "stored": False,
        "storage": None,
        "persisted_source": None,
        "required": False,
    }
    binding_status = (
        GITHUB_BINDING_PENDING_STATUS
        if normalized == GITHUB_ADOPTION_APP_BINDING
        else GITHUB_BINDING_BACKLOG_ONLY_STATUS
    )

    return {
        "choice": normalized,
        "explicit": explicit,
        "github_repo": github_repo,
        "automation_enabled": bool(
            github_repo and normalized == GITHUB_ADOPTION_APP_BINDING
        ),
        "requires_explicit_choice": False,
        "machine_github_credential_promoted": False,
        "secret": secret,
        "binding": {
            "status": binding_status,
            "repo": github_repo,
            "requires_app_installation": normalized == GITHUB_ADOPTION_APP_BINDING,
        },
    }


def should_store_project_github_binding(
    github_adoption: Mapping[str, Any] | None,
) -> bool:
    return False


def github_capabilities_payload(
    github_repo: str | None,
    github_adoption: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not github_repo or not github_adoption:
        return None
    if github_adoption.get("choice") != GITHUB_ADOPTION_APP_BINDING:
        return None
    return {"github": {"settings": {"repo": github_repo, "auth": "github_app"}}}


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
    token_value: str | None,
) -> str:
    if choice is not None:
        if choice in GITHUB_ADOPTION_LEGACY_CHOICES:
            raise ProjectGithubAdoptionError(
                f"--github-adoption {choice} is no longer supported. Use "
                "--github-adoption app-binding or --github-adoption backlog-only."
            )
        if choice == "skip":
            return GITHUB_ADOPTION_BACKLOG_ONLY
        if choice not in GITHUB_ADOPTION_CHOICES:
            raise ProjectGithubAdoptionError(
                "unknown GitHub adoption choice: "
                f"{choice}; expected one of app-binding, backlog-only, skip"
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
    if github_adoption.get("choice") == GITHUB_ADOPTION_APP_BINDING:
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
    if not github_repo:
        status = "skipped-no-repo"
    elif github_adoption.get("automation_enabled"):
        status = "pending-app-installation"
    else:
        status = "skipped-by-adoption-choice"
    return [
        {
            "category": category,
            "target": github_repo,
            "status": status,
            "items": [],
        }
        for category in GITHUB_AUTOMATION_CATEGORIES
    ]


def _project_value(project: Mapping[str, Any], key: str) -> Any:
    value = project.get(key)
    if value is not None:
        return value
    if key == "github_repo":
        return project.get("githubRepo")
    return None
