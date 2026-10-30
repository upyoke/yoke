"""Project sync-policy behavior when adding a GitHub App repo binding."""

from __future__ import annotations

from dataclasses import replace

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain.github_app_user_verification import (
    VerifiedProjectGitHubBinding,
)
from yoke_core.domain.project_github_binding import cmd_bind_project_repo, cmd_unbind_project_repo


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
        repository_is_private=True,
        installation_status="active",
    )


def test_bind_preserves_intentional_disabled(monkeypatch):
    with pg_testdb.test_database() as database:
        db_name = database.info.dbname
        conn = pg_testdb.connect_test_database(db_name)
        try:
            pass
            conn.execute(
                "UPDATE projects SET github_sync_mode='disabled' "
                "WHERE slug='externalwebapp'"
            )
            conn.commit()
        finally:
            conn.close()

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
        assert status["github_sync_mode"] == "disabled"
        assert status["automation"] == {"available": True, "reason": "bound"}


@pytest.mark.parametrize("private", [True, False])
@pytest.mark.parametrize("previous", ["enabled", "disabled"])
def test_binding_sync_change_receipt(private, previous):
    with pg_testdb.test_database() as database:
        conn = pg_testdb.connect_test_database(database.info.dbname)
        try:
            conn.execute(
                "UPDATE projects SET github_sync_mode=%s WHERE slug='externalwebapp'",
                (previous,),
            )
            status = cmd_bind_project_repo(
                "externalwebapp", installation_id="12345", repository_id="4567",
                github_repo="example-org/externalwebapp",
                expected_api_url="https://api.github.com",
                github_user_access_token="github-user-token", conn=conn,
                verifier=lambda **kwargs: replace(
                    _verified_binding(), repository_is_private=private,
                ),
            )
            current = previous if private else "disabled"
            assert status["previous_sync_mode"] == previous
            assert status["sync_mode"] == current
            assert status["github_sync_mode"] == current
            notice = status["sync_mode_notice"]
            if previous != current:
                assert "Issue sync was turned off" in notice
                assert "--github-sync-mode enabled --allow-public-github-sync" in notice
                assert "bind a repository again" not in notice
            else:
                assert notice is None
        finally:
            conn.close()


@pytest.mark.parametrize("private", [True, False])
@pytest.mark.parametrize("previous", ["enabled", "disabled"])
def test_unbind_sync_change_receipt(private, previous):
    with pg_testdb.test_database() as database:
        conn = pg_testdb.connect_test_database(database.info.dbname)
        try:
            cmd_bind_project_repo(
                "externalwebapp", installation_id="12345", repository_id="4567",
                github_repo="example-org/externalwebapp",
                expected_api_url="https://api.github.com",
                github_user_access_token="github-user-token", conn=conn,
                verifier=lambda **kwargs: replace(
                    _verified_binding(), repository_is_private=private,
                ),
            )
            conn.execute(
                "UPDATE projects SET github_sync_mode=%s WHERE slug='externalwebapp'",
                (previous,),
            )
            status = cmd_unbind_project_repo("externalwebapp", conn=conn)
            assert status["bound"] is False
            assert status["previous_sync_mode"] == previous
            assert status["sync_mode"] == "disabled"
            assert status["github_sync_mode"] == "disabled"
            notice = status["sync_mode_notice"]
            if previous == "enabled":
                assert "bind a repository again, then run yoke projects update" in notice
                assert "--slug externalwebapp" in notice
                assert "--name " in notice
                assert "--github-sync-mode enabled" in notice
                assert ("--allow-public-github-sync" in notice) is (not private)
            else:
                assert notice is None
        finally:
            conn.close()
