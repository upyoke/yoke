from __future__ import annotations

import json

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_schema
from yoke_core.domain import db_backend
from yoke_core.domain.github_app_user_verification import (
    VerifiedProjectGitHubBinding,
)
from yoke_core.domain.project_github_binding import cmd_bind_project_repo


_PERMISSIONS = {
    "metadata": "read",
    "issues": "write",
    "pull_requests": "write",
    "contents": "write",
    "actions": "write",
    "checks": "read",
    "workflows": "write",
    "secrets": "write",
    "variables": "write",
}


def _verified() -> VerifiedProjectGitHubBinding:
    return VerifiedProjectGitHubBinding(
        installation_id="12345",
        account_id="9988",
        account_login="Example-Org",
        account_type="Organization",
        repository_selection="selected",
        permissions=_PERMISSIONS,
        repository_id="4567",
        github_repo="Example-Org/Buzz",
        default_branch="trunk",
    )


def _bind() -> None:
    cmd_bind_project_repo(
        "buzz",
        installation_id="12345",
        repository_id="4567",
        github_repo="Example-Org/Buzz",
        expected_api_url="https://api.github.com",
        github_user_access_token="github-user-token",
        verifier=lambda **kwargs: _verified(),
    )


def _settings(db_name: str) -> dict[str, object]:
    conn = pg_testdb.connect_test_database(db_name)
    try:
        row = conn.execute(
            "SELECT settings FROM project_capabilities "
            "WHERE project_id=2 AND type='github'",
        ).fetchone()
        return json.loads(row["settings"])
    finally:
        conn.close()


def test_binding_projects_current_capability_fields_and_drops_unknowns(
    monkeypatch,
) -> None:
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

        _bind()
        assert _settings(db_name) == {
            "repo_owner": "Example-Org",
            "repo_name": "Buzz",
            "installation_id": "12345",
            "repository_id": "4567",
            "api_url": "https://api.github.com",
            "permissions": _PERMISSIONS,
        }

        conn = pg_testdb.connect_test_database(db_name)
        try:
            conn.execute(
                "UPDATE project_capabilities SET settings=%s "
                "WHERE project_id=2 AND type='github'",
                (json.dumps({
                    "repo_owner": "stale-owner",
                    "repo_name": "stale-repo",
                    "installation_id": "1",
                    "repository_id": "2",
                    "api_url": "https://github.example/api/v3",
                    "permissions": {"administration": "write"},
                    "ci_oidc_manage_provider": False,
                    "unrecognized_secret": "must-not-survive",
                    "unrecognized_setting": "must-not-survive",
                }),),
            )
            conn.commit()
        finally:
            conn.close()

        _bind()
        assert _settings(db_name) == {
            "ci_oidc_manage_provider": False,
            "repo_owner": "Example-Org",
            "repo_name": "Buzz",
            "installation_id": "12345",
            "repository_id": "4567",
            "api_url": "https://api.github.com",
            "permissions": _PERMISSIONS,
        }
    finally:
        pg_testdb.drop_test_database(db_name)
