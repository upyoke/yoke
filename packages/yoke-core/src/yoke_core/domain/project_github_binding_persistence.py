"""Atomic persistence helpers for GitHub App project bindings."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one


class ProjectGithubBindingError(ValueError):
    """Raised when GitHub App binding state cannot be read or written."""


class InstallationOriginConflict(ProjectGithubBindingError):
    """Raised when one installation id is observed on multiple API origins."""


class RepositoryBindingConflict(ProjectGithubBindingError):
    """Raised when a repository is already owned by another project."""


def persist_verified_installation(
    conn: Any,
    *,
    placeholder: str,
    installation_id: str,
    api_url: str,
    account_id: str,
    account_login: str,
    account_type: str,
    repository_selection: str,
    permissions: str,
    status: str,
    verified_at: str,
    last_error: Optional[str],
) -> None:
    """Upsert an installation while atomically preserving its API origin."""
    existing = query_one(
        conn,
        f"SELECT api_url FROM github_app_installations "
        f"WHERE installation_id={placeholder}",
        (installation_id,),
    )
    if existing is not None and str(existing["api_url"] or "") != api_url:
        raise InstallationOriginConflict

    write = conn.execute(
        "INSERT INTO github_app_installations "
        "(installation_id, api_url, account_id, account_login, account_type, "
        "repository_selection, permissions, status, last_verified_at, "
        "last_error, created_at, updated_at) "
        f"VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, "
        f"{placeholder}, {placeholder}, {placeholder}, {placeholder}, "
        f"{placeholder}, {placeholder}, {placeholder}, {placeholder}) "
        "ON CONFLICT(installation_id) DO UPDATE SET "
        "api_url=EXCLUDED.api_url, "
        "account_id=EXCLUDED.account_id, "
        "account_login=EXCLUDED.account_login, "
        "account_type=EXCLUDED.account_type, "
        "repository_selection=EXCLUDED.repository_selection, "
        "permissions=EXCLUDED.permissions, "
        "status=EXCLUDED.status, "
        "last_verified_at=EXCLUDED.last_verified_at, "
        "last_error=EXCLUDED.last_error, "
        "updated_at=EXCLUDED.updated_at "
        "WHERE github_app_installations.api_url=EXCLUDED.api_url",
        (
            installation_id,
            api_url,
            account_id,
            account_login,
            account_type,
            repository_selection,
            permissions,
            status,
            verified_at,
            last_error,
            verified_at,
            verified_at,
        ),
    )
    if write.rowcount == 0:
        raise InstallationOriginConflict


def persist_project_binding(
    conn: Any,
    *,
    placeholder: str,
    project_id: int,
    installation_id: str,
    repository_id: str,
    api_url: str,
    github_repo: str,
    default_branch: Optional[str],
    status: str,
    permissions: str,
    verified_at: str,
    last_error: Optional[str],
) -> None:
    """Upsert one project's repository binding with unique ownership."""
    try:
        conn.execute(
            "INSERT INTO project_github_repo_bindings "
            "(project_id, installation_id, repository_id, api_url, github_repo, "
            "default_branch, status, permissions, last_verified_at, last_error, "
            "created_at, updated_at) "
            f"VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, "
            f"{placeholder}, {placeholder}, {placeholder}, {placeholder}, "
            f"{placeholder}, {placeholder}, {placeholder}, {placeholder}) "
            "ON CONFLICT(project_id) DO UPDATE SET "
            "installation_id=EXCLUDED.installation_id, "
            "repository_id=EXCLUDED.repository_id, "
            "api_url=EXCLUDED.api_url, "
            "github_repo=EXCLUDED.github_repo, "
            "default_branch=EXCLUDED.default_branch, "
            "status=EXCLUDED.status, "
            "permissions=EXCLUDED.permissions, "
            "last_verified_at=EXCLUDED.last_verified_at, "
            "last_error=EXCLUDED.last_error, "
            "updated_at=EXCLUDED.updated_at",
            (
                project_id,
                installation_id,
                repository_id,
                api_url,
                github_repo,
                default_branch,
                status,
                permissions,
                verified_at,
                last_error,
                verified_at,
                verified_at,
            ),
        )
    except db_backend.integrity_error_types(conn) as exc:
        raise RepositoryBindingConflict from exc


def clean_required(value: Any, label: str) -> str:
    """Return a normalized required binding value."""
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ProjectGithubBindingError(f"{label} is required")
    return cleaned


def clean_optional(value: Any) -> Optional[str]:
    """Return a normalized optional binding value."""
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned if cleaned else None
