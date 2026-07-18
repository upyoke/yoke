"""Project sync-policy behavior when adding a GitHub App repo binding."""

from __future__ import annotations

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_schema
from yoke_core.domain import db_backend
from yoke_core.domain.github_app_user_verification import (
    VerifiedProjectGitHubBinding,
)
from yoke_core.domain.project_github_binding import cmd_bind_project_repo


def _verified_binding() -> VerifiedProjectGitHubBinding:
    return VerifiedProjectGitHubBinding(
        installation_id="12345",
        account_id="9988",
        account_login="Example-Org",
        account_type="Organization",
        repository_selection="selected",
        permissions={
            "metadata": "read",
            "issues": "write",
            "pull_requests": "write",
            "contents": "write",
            "actions": "write",
            "checks": "read",
            "workflows": "write",
            "secrets": "write",
            "actions_variables": "write",
        },
        repository_id="4567",
        github_repo="example-org/externalwebapp",
        default_branch="trunk",
        installation_status="active",
    )


def test_bind_preserves_intentional_backlog_only(monkeypatch):
    db_name = pg_testdb.create_test_database()
    try:
        conn = pg_testdb.connect_test_database(db_name)
        try:
            apply_fixture_schema(conn)
            conn.execute(
                "UPDATE projects SET github_sync_mode='backlog_only' "
                "WHERE slug='externalwebapp'"
            )
            conn.commit()
        finally:
            conn.close()
        monkeypatch.setenv(
            db_backend.PG_DSN_ENV,
            pg_testdb.dsn_for_test_database(db_name),
        )

        status = cmd_bind_project_repo(
            "externalwebapp",
            installation_id="12345",
            github_repo="example-org/externalwebapp",
            repository_id="4567",
            expected_api_url="https://api.github.com",
            github_user_access_token="github-user-token",
            verifier=lambda **kwargs: _verified_binding(),
        )

        assert status["bound"] is True
        assert status["binding"]["status"] == "active"
        assert status["github_sync_mode"] == "backlog_only"
        assert status["automation"] == {"available": True, "reason": "bound"}
    finally:
        pg_testdb.drop_test_database(db_name)
