"""Shared Postgres fixtures for project GitHub auth tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.file_test_db import init_test_db
from yoke_contracts.github_origin import validate_github_api_endpoint
from yoke_contracts.github_app_installation_permissions import (
    REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS,
)
from yoke_core.domain import db_backend, projects, project_github_auth_tokens
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.github_app_control_plane import GitHubAppControlPlaneConfig
from yoke_core.domain.github_app_token_models import InstallationToken
from yoke_core.domain.github_app_user_verification import VerifiedProjectGitHubBinding
from yoke_core.domain.project_github_binding import cmd_bind_project_repo
from yoke_core.domain.project_seed_test_helpers import seed_project_identities


def _apply_schema() -> None:
    return None


@pytest.fixture
def db_path(tmp_path: Path):
    with init_test_db(tmp_path, apply_schema=_apply_schema) as path:
        yield path


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _init_with_projects(db_path: str) -> None:
    projects.cmd_init(db_path=db_path)
    conn = connect(db_path)
    try:
        seed_project_identities(conn)
    finally:
        conn.close()


_CONTROL_PLANE_CONFIG = GitHubAppControlPlaneConfig(
    issuer="Iv1.local",
    private_key_pem="test-private-key",
    endpoint=validate_github_api_endpoint("https://api.github.com"),
    private_key_file="/run/secrets/yoke-github-app-key",
)


@pytest.fixture(autouse=True)
def control_plane_config(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        project_github_auth_tokens,
        "load_github_app_control_plane_config",
        lambda: _CONTROL_PLANE_CONFIG,
    )


def _bind_yoke(
    db_path: str,
    *,
    repository_id: str | None = "4567",
    permissions: dict[str, str] | None = None,
    installation_status: str = "active",
    binding_status: str = "active",
) -> None:
    selected_permissions = permissions or dict(
        REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS
    )
    verified = VerifiedProjectGitHubBinding(
        installation_id="12345",
        account_id="9988",
        account_login="upyoke",
        account_type="Organization",
        repository_selection="selected",
        permissions=selected_permissions,
        repository_id=str(repository_id or "4567"),
        github_repo="upyoke/yoke",
        default_branch="main",
    )
    cmd_bind_project_repo(
        "yoke",
        installation_id="12345",
        github_repo="upyoke/yoke",
        repository_id=str(repository_id or "4567"),
        expected_api_url="https://api.github.com",
        github_user_access_token="github-user-token",
        verifier=lambda **kwargs: verified,
        db_path=db_path,
    )
    if installation_status == "active" and binding_status == "active":
        return
    conn = connect(db_path)
    try:
        placeholder = _p(conn)
        conn.execute(
            f"UPDATE github_app_installations SET status={placeholder} "
            f"WHERE installation_id={placeholder}",
            (installation_status, "12345"),
        )
        conn.execute(
            f"UPDATE project_github_repo_bindings SET status={placeholder} "
            f"WHERE installation_id={placeholder}",
            (binding_status, "12345"),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def app_bound_db(db_path: str) -> str:
    _init_with_projects(db_path)
    _bind_yoke(db_path)
    return db_path


def _minted(token: str = "ghs_install") -> InstallationToken:
    return InstallationToken(
        token=token,
        expires_at=datetime(2026, 7, 9, 18, 0, tzinfo=timezone.utc),
    )


__all__ = [
    "_CONTROL_PLANE_CONFIG",
    "_bind_yoke",
    "_init_with_projects",
    "_minted",
    "_p",
    "app_bound_db",
    "control_plane_config",
    "db_path",
]
