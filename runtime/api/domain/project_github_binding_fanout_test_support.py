# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Mapping

import pytest

from runtime.api.fixtures import pg_testdb

from yoke_core.domain import project_github_binding_state, projects

from yoke_core.domain.github_app_user_verification import (
    VerifiedProjectGitHubBinding,
)

from yoke_core.domain.project_github_auth import (
    MissingPermission,
    bind_local_github_user_token_provider,
    resolve_project_github_auth,
)

from yoke_core.domain.project_github_binding import (
    ProjectGithubBindingError,
    cmd_bind_project_repo,
    cmd_project_github_binding_status,
)

from yoke_core.domain.project_renderer_settings import load_project_renderer_settings

_FULL_PERMISSIONS = {
    "metadata": "read",
    "issues": "write",
    "pull_requests": "write",
    "contents": "write",
    "actions": "write",
    "checks": "read",
    "statuses": "read",
    "workflows": "write",
    "secrets": "write",
    "actions_variables": "write",
}


def _verified(
    github_repo: str,
    repository_id: str,
    *,
    permissions: Mapping[str, str],
) -> VerifiedProjectGitHubBinding:
    return VerifiedProjectGitHubBinding(
        installation_id="12345",
        account_id="9988",
        account_login="Example-Org",
        account_type="Organization",
        repository_selection="selected",
        permissions=permissions,
        repository_id=repository_id,
        github_repo=github_repo,
        default_branch="main",
        repository_is_private=True,
    )


def _bind(
    project: str,
    github_repo: str,
    repository_id: str,
    *,
    permissions: Mapping[str, str],
) -> None:
    cmd_bind_project_repo(
        project,
        installation_id="12345",
        repository_id=repository_id,
        github_repo=github_repo,
        expected_api_url="https://api.github.com",
        github_user_access_token="github-user-token",
        verifier=lambda **kwargs: _verified(
            github_repo,
            repository_id,
            permissions=permissions,
        ),
    )


@pytest.fixture
def bound_yoke_db(monkeypatch):
    with pg_testdb.test_database() as database:
        db_name = database.info.dbname
        _bind("yoke", "Example-Org/Yoke", "4567", permissions=_FULL_PERMISSIONS)
        yield db_name
