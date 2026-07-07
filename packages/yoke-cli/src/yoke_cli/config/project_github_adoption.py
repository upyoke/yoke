"""GitHub adoption reporting for project onboarding."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


class ProjectGithubAdoptionError(RuntimeError):
    """Project GitHub adoption cannot proceed."""


GITHUB_ADOPTION_CHOICES = (
    "temporary-only",
    "store-token",
    "different-token",
    "skip",
)
GITHUB_ADOPTION_STORE_CHOICES = ("store-token", "different-token")
GITHUB_ADOPTION_UNSELECTED = "unselected"
GITHUB_SECRET_REF = "capability_secrets:github.token"
GITHUB_SECRET_SOURCE = "literal"
GITHUB_TOKEN_KEY = "token"
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
    normalized = _normalize_github_adoption_choice(
        choice=choice, github_repo=github_repo, token_value=token_value,
    )
    if not github_repo and normalized != "skip":
        raise ProjectGithubAdoptionError(
            "GitHub adoption requires --github-repo OWNER/REPO"
        )
    if normalized == "skip" and token_value:
        raise ProjectGithubAdoptionError(
            "GitHub token input cannot be combined with --github-adoption skip"
        )
    if normalized in GITHUB_ADOPTION_STORE_CHOICES and apply and not token_value:
        raise ProjectGithubAdoptionError(
            f"--github-adoption {normalized} requires a GitHub token source"
        )
    if normalized == GITHUB_ADOPTION_UNSELECTED and apply:
        raise ProjectGithubAdoptionError(
            "choose --github-adoption temporary-only, store-token, "
            "different-token, or skip before applying GitHub project adoption"
        )

    will_store = normalized in GITHUB_ADOPTION_STORE_CHOICES and bool(token_value)
    secret: dict[str, Any] = {
        "provided": bool(token_value),
        "import_method": token_import_method,
        "stored": will_store,
        "storage": GITHUB_SECRET_REF if will_store else None,
        "persisted_source": GITHUB_SECRET_SOURCE if will_store else None,
        "required": normalized in GITHUB_ADOPTION_STORE_CHOICES,
    }
    if normalized == "temporary-only":
        secret["stored"] = False
        secret["storage"] = None
        secret["persisted_source"] = None

    return {
        "choice": normalized,
        "explicit": explicit,
        "github_repo": github_repo,
        "automation_enabled": bool(
            github_repo and normalized not in ("skip", GITHUB_ADOPTION_UNSELECTED)
        ),
        "requires_explicit_choice": (
            bool(github_repo) and normalized == GITHUB_ADOPTION_UNSELECTED
        ),
        "machine_github_credential_promoted": False,
        "secret": secret,
    }


def should_store_project_github_token(
    github_adoption: Mapping[str, Any] | None,
) -> bool:
    if not github_adoption:
        return False
    secret = github_adoption.get("secret")
    return isinstance(secret, Mapping) and secret.get("stored") is True


def github_capabilities_payload(
    github_repo: str | None,
    github_adoption: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not github_repo or not github_adoption:
        return None
    if github_adoption.get("choice") not in GITHUB_ADOPTION_STORE_CHOICES:
        return None
    return {"github": {"settings": {"repo": github_repo}}}


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
        if choice not in GITHUB_ADOPTION_CHOICES:
            raise ProjectGithubAdoptionError(
                "unknown GitHub adoption choice: "
                f"{choice}; expected one of {', '.join(GITHUB_ADOPTION_CHOICES)}"
            )
        return choice
    if not github_repo:
        return "skip"
    if token_value:
        return "store-token"
    return GITHUB_ADOPTION_UNSELECTED


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
    if should_store_project_github_token(github_adoption):
        secret = github_adoption.get("secret") or {}
        writes.append({
            "surface": "projects.capability_secret.set",
            "capability": "github",
            "key": GITHUB_TOKEN_KEY,
            "storage": GITHUB_SECRET_REF,
            "persisted_source": GITHUB_SECRET_SOURCE,
            "import_method": secret.get("import_method"),
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
        status = "preview-only-no-mutator"
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
