"""Authorization and state helpers for local-mode resync tests."""

from __future__ import annotations

from contextlib import contextmanager

from yoke_contracts.github_app_installation_permissions import (
    REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS,
)

from yoke_core.domain.project_github_auth import (
    bind_local_github_user_token_provider,
)
from yoke_core.domain.github_app_user_verification import (
    VerifiedProjectGitHubBinding,
)
from yoke_core.domain.project_github_binding import cmd_bind_project_repo

from runtime.api.fixtures import pg_testdb


PROJECT_REPO = "upyoke/yoke"


def read_github_issue(universe, item_id: int):
    conn = pg_testdb.connect_test_database(universe.db_name)
    try:
        row = conn.execute(
            "SELECT github_issue FROM items WHERE id = %s", (item_id,),
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row is not None else None


def seed_project_github_binding(conn, transient_user_token: str) -> None:
    verified = VerifiedProjectGitHubBinding(
        installation_id="12345",
        account_id="9988",
        account_login="upyoke",
        account_type="Organization",
        repository_selection="selected",
        permissions=dict(REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS),
        repository_id="4567",
        github_repo=PROJECT_REPO,
        default_branch="main",
    )
    cmd_bind_project_repo(
        "yoke",
        installation_id=verified.installation_id,
        repository_id=verified.repository_id,
        github_repo=verified.github_repo,
        expected_api_url="https://api.github.com",
        github_user_access_token=transient_user_token,
        verifier=lambda **_kwargs: verified,
        conn=conn,
    )


@contextmanager
def local_user_authorization(universe):
    with bind_local_github_user_token_provider(
        lambda: universe.token,
        api_url="https://api.github.com",
    ):
        yield


__all__ = [
    "PROJECT_REPO",
    "local_user_authorization",
    "read_github_issue",
    "seed_project_github_binding",
]
