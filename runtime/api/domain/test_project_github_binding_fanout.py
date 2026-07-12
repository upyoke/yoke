from __future__ import annotations

from typing import Mapping

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_schema
from yoke_core.domain import db_backend, project_github_binding_state, projects
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
from yoke_core.domain.projects_upsert import cmd_upsert


_FULL_PERMISSIONS = {
    "metadata": "read",
    "issues": "write",
    "pull_requests": "write",
    "contents": "write",
    "actions": "write",
    "checks": "read",
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
            github_repo, repository_id, permissions=permissions,
        ),
    )


@pytest.fixture
def bound_yoke_db(monkeypatch):
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
        _bind("yoke", "Example-Org/Yoke", "4567", permissions=_FULL_PERMISSIONS)
        yield db_name
    finally:
        pg_testdb.drop_test_database(db_name)


def test_installation_permission_refresh_fans_out_downgrade_and_upgrade(
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
        _bind("yoke", "Example-Org/Yoke", "4567", permissions=_FULL_PERMISSIONS)
        _bind("buzz", "Example-Org/Buzz", "4568", permissions=_FULL_PERMISSIONS)
        projects.cmd_capability_merge_settings(
            "yoke", "github", {"ci_oidc_manage_provider": False},
        )

        _bind(
            "buzz",
            "Example-Org/Buzz",
            "4568",
            permissions={"metadata": "read", "issues": "read"},
        )

        downgraded = cmd_project_github_binding_status("yoke")
        assert downgraded["binding"]["status"] == "pending"
        assert downgraded["github_sync_mode"] == "enabled"
        assert downgraded["permission_status"]["status"] == "missing"
        assert downgraded["automation"] == {
            "available": False,
            "reason": "missing_permissions",
        }
        with pytest.raises(MissingPermission):
            resolve_project_github_auth("yoke")
        assert load_project_renderer_settings("yoke").capabilities["github"] == {
            "api_url": "https://api.github.com",
            "ci_oidc_manage_provider": False,
            "installation_id": "12345",
            "permissions": {"metadata": "read", "issues": "read"},
            "repo_name": "Yoke",
            "repo_owner": "Example-Org",
            "repository_id": "4567",
        }
        assert load_project_renderer_settings("buzz").capabilities["github"] == {
            "api_url": "https://api.github.com",
            "installation_id": "12345",
            "permissions": {"metadata": "read", "issues": "read"},
            "repo_name": "Buzz",
            "repo_owner": "Example-Org",
            "repository_id": "4568",
        }

        _bind("buzz", "Example-Org/Buzz", "4568", permissions=_FULL_PERMISSIONS)

        upgraded = cmd_project_github_binding_status("yoke")
        assert upgraded["binding"]["status"] == "active"
        assert upgraded["github_sync_mode"] == "enabled"
        assert upgraded["permission_status"]["status"] == "satisfied"
        assert upgraded["automation"] == {"available": True, "reason": "bound"}
        with bind_local_github_user_token_provider(
            lambda: "github-user-token", api_url="https://api.github.com",
        ):
            resolved = resolve_project_github_auth("yoke")
        assert resolved.repo == "Example-Org/Yoke"
        assert resolved.permissions == _FULL_PERMISSIONS
        upgraded_capability = load_project_renderer_settings(
            "yoke"
        ).capabilities["github"]
        assert upgraded_capability["permissions"] == _FULL_PERMISSIONS
        assert upgraded_capability["repo_owner"] == "Example-Org"
        assert upgraded_capability["repo_name"] == "Yoke"
        assert upgraded_capability["repository_id"] == "4567"
        assert upgraded_capability["api_url"] == "https://api.github.com"
        assert upgraded_capability["ci_oidc_manage_provider"] is False
    finally:
        pg_testdb.drop_test_database(db_name)


def test_installation_refresh_preserves_intentional_backlog_only(
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
        _bind("yoke", "Example-Org/Yoke", "4567", permissions=_FULL_PERMISSIONS)
        _bind("buzz", "Example-Org/Buzz", "4568", permissions=_FULL_PERMISSIONS)
        projects.cmd_update("yoke", "github_sync_mode", "backlog_only")

        _bind(
            "buzz",
            "Example-Org/Buzz",
            "4568",
            permissions={"metadata": "read", "issues": "read"},
        )

        downgraded = cmd_project_github_binding_status("yoke")
        assert downgraded["github_sync_mode"] == "backlog_only"
        assert downgraded["binding"]["status"] == "pending"
        assert downgraded["automation"] == {
            "available": False,
            "reason": "missing_permissions",
        }

        _bind("buzz", "Example-Org/Buzz", "4568", permissions=_FULL_PERMISSIONS)

        recovered = cmd_project_github_binding_status("yoke")
        assert recovered["github_sync_mode"] == "backlog_only"
        assert recovered["binding"]["status"] == "active"
        assert recovered["automation"] == {"available": True, "reason": "bound"}
    finally:
        pg_testdb.drop_test_database(db_name)


def test_installation_permission_fanout_rolls_back_projection_failure(
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
        _bind("yoke", "Example-Org/Yoke", "4567", permissions=_FULL_PERMISSIONS)
        _bind("buzz", "Example-Org/Buzz", "4568", permissions=_FULL_PERMISSIONS)

        original_builder = (
            project_github_binding_state.build_github_capability_settings
        )
        projection_count = 0

        def fail_second_projection(*args, **kwargs):
            nonlocal projection_count
            projection_count += 1
            if projection_count == 2:
                raise RuntimeError("projection write failed")
            return original_builder(*args, **kwargs)

        monkeypatch.setattr(
            project_github_binding_state,
            "build_github_capability_settings",
            fail_second_projection,
        )
        with pytest.raises(RuntimeError, match="projection write failed"):
            _bind(
                "buzz",
                "Example-Org/Buzz",
                "4568",
                permissions={"metadata": "read", "issues": "read"},
            )

        yoke_status = cmd_project_github_binding_status("yoke")
        assert yoke_status["binding"]["status"] == "active"
        assert yoke_status["github_sync_mode"] == "enabled"
        assert yoke_status["permission_status"]["status"] == "satisfied"
        assert load_project_renderer_settings(
            "yoke"
        ).capabilities["github"]["permissions"] == _FULL_PERMISSIONS
    finally:
        pg_testdb.drop_test_database(db_name)


def test_repository_identity_cannot_bind_a_second_project_after_rename(
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
        _bind("yoke", "Example-Org/Yoke", "4567", permissions=_FULL_PERMISSIONS)

        with pytest.raises(
            ProjectGithubBindingError,
            match="already bound to another project",
        ):
            _bind(
                "buzz",
                "Example-Org/Yoke-Renamed",
                "4567",
                permissions=_FULL_PERMISSIONS,
            )

        assert cmd_project_github_binding_status("buzz")["bound"] is False
        assert cmd_project_github_binding_status("yoke")["bound"] is True
    finally:
        pg_testdb.drop_test_database(db_name)


def test_project_upsert_rejects_repo_change_after_binding(bound_yoke_db) -> None:
    with pytest.raises(ValueError, match="binding-owned"):
        cmd_upsert(
            slug="yoke",
            name="Yoke",
            github_repo="other-org/other-repo",
            mode="update",
        )
    assert projects.cmd_get("yoke", field="github_repo") == "Example-Org/Yoke"


def test_project_upsert_accepts_equivalent_repo_and_keeps_bound_projection(
    bound_yoke_db,
) -> None:
    cmd_upsert(
        slug="yoke",
        name="Yoke Renamed",
        github_repo="https://github.com/example-org/yoke.git",
        mode="update",
    )
    assert projects.cmd_get("yoke", field="github_repo") == "Example-Org/Yoke"


def test_legacy_project_field_update_cannot_bypass_binding(bound_yoke_db) -> None:
    with pytest.raises(ValueError, match="binding-owned"):
        projects.cmd_update("yoke", "github_repo", "other-org/other-repo")
