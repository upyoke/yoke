"""Canonical GitHub App binding fixture for update-status subprocess tests."""

from __future__ import annotations

import json

from yoke_contracts.github_app_installation_permissions import (
    REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS,
)


def seed_github_app_auth(conn, placeholder: str, now: str) -> None:
    permissions = json.dumps(
        dict(REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS)
    )
    conn.execute(
        "INSERT INTO github_app_installations "
        "(installation_id, account_id, account_login, account_type, "
        "permissions, status, created_at, updated_at) "
        f"VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, "
        f"{placeholder}, 'active', {placeholder}, {placeholder})",
        ("12345", "9988", "test-org", "Organization", permissions, now, now),
    )
    for project_id, repo, repository_id in (
        (1, "upyoke/yoke", "4567"),
        (2, "example-org/externalwebapp", "4568"),
    ):
        conn.execute(
            "INSERT INTO project_github_repo_bindings "
            "(project_id, installation_id, repository_id, github_repo, "
            "status, permissions, created_at, updated_at) "
            f"VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, "
            f"'active', {placeholder}, {placeholder}, {placeholder})",
            (project_id, "12345", repository_id, repo, permissions, now, now),
        )
        owner, name = repo.split("/", 1)
        conn.execute(
            "INSERT INTO project_capabilities (project_id, type, settings) "
            f"VALUES ({placeholder}, 'github', {placeholder})",
            (project_id, json.dumps({
                "repo_owner": owner,
                "repo_name": name,
                "installation_id": "12345",
                "repository_id": repository_id,
            })),
        )


__all__ = ("seed_github_app_auth",)
