"""Project unbind and verified rebind preserve connection-layer boundaries."""

from __future__ import annotations

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_schema
from yoke_core.domain import db_backend
from yoke_core.domain.github_app_user_verification import (
    VerifiedProjectGitHubBinding,
)
from yoke_core.domain.project_github_binding import (
    cmd_bind_project_repo,
    cmd_unbind_project_repo,
)
from yoke_core.domain.projects_crud import cmd_update


def _verified(repository_id: str, github_repo: str) -> VerifiedProjectGitHubBinding:
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
        repository_id=repository_id,
        github_repo=github_repo,
        default_branch="main",
        installation_status="active",
    )


def _bind(project: str, repository_id: str, github_repo: str) -> dict:
    return cmd_bind_project_repo(
        project,
        installation_id="12345",
        repository_id=repository_id,
        github_repo=github_repo,
        expected_api_url="https://api.github.com",
        github_user_access_token="short-lived-user-token",
        verifier=lambda **_kwargs: _verified(repository_id, github_repo),
    )


def test_unbind_then_rebind_changes_only_the_selected_project(monkeypatch) -> None:
    db_name = pg_testdb.create_test_database()
    try:
        conn = pg_testdb.connect_test_database(db_name)
        try:
            apply_fixture_schema(conn)
        finally:
            conn.close()
        monkeypatch.setenv(
            db_backend.PG_DSN_ENV,
            pg_testdb.dsn_for_test_database(db_name),
        )

        _bind("buzz", "4567", "Example-Org/Buzz")
        _bind("yoke", "4568", "Example-Org/Yoke")
        conn = pg_testdb.connect_test_database(db_name)
        try:
            conn.execute(
                "INSERT INTO capability_secrets "
                "(project_id, type, key, value, source) VALUES "
                "(2, ' GitHub ', 'token', 'retired-buzz-token', 'literal'), "
                "(2, 'docker', 'registry', 'keep-buzz-registry', 'literal'), "
                "(1, 'github', 'token', 'keep-yoke-token', 'literal')"
            )
            conn.commit()
        finally:
            conn.close()

        unbound = cmd_unbind_project_repo("buzz")

        assert unbound["bound"] is False
        assert unbound["github_repo"] == ""
        assert unbound["github_sync_mode"] == "backlog_only"
        conn = pg_testdb.connect_test_database(db_name)
        try:
            project = conn.execute(
                "SELECT github_repo, github_sync_mode FROM projects WHERE slug='buzz'"
            ).fetchone()
            assert dict(project) == {
                "github_repo": None,
                "github_sync_mode": "backlog_only",
            }
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM project_github_repo_bindings "
                    "WHERE project_id=2"
                ).fetchone()[0]
                == 0
            )
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM project_capabilities "
                    "WHERE project_id=2 AND type='github'"
                ).fetchone()[0]
                == 0
            )
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM capability_secrets "
                    "WHERE project_id=2 AND LOWER(TRIM(type))='github'"
                ).fetchone()[0]
                == 0
            )
            unrelated = conn.execute(
                "SELECT value FROM capability_secrets "
                "WHERE project_id=2 AND type='docker' AND key='registry'"
            ).fetchone()
            assert unrelated[0] == "keep-buzz-registry"
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM capability_secrets "
                    "WHERE project_id=1 AND type='github' AND key='token'"
                ).fetchone()[0]
                == 1
            )
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM github_app_installations "
                    "WHERE installation_id='12345'"
                ).fetchone()[0]
                == 1
            )
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM project_github_repo_bindings "
                    "WHERE project_id=1 AND repository_id='4568'"
                ).fetchone()[0]
                == 1
            )
        finally:
            conn.close()

        rebound = _bind("buzz", "4567", "Example-Org/Buzz")

        assert rebound["bound"] is True
        assert rebound["binding"]["status"] == "active"
        assert rebound["github_sync_mode"] == "backlog_only"
        assert cmd_update("buzz", "github_sync_mode", "enabled").startswith(
            "Updated project"
        )
    finally:
        pg_testdb.drop_test_database(db_name)
