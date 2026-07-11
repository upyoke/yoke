from __future__ import annotations

from unittest import mock

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_schema
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import db_backend
from yoke_core.domain.github_app_user_verification import (
    VerifiedProjectGitHubBinding,
)
from yoke_core.domain import project_github_binding as binding_domain
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.handlers.project_github_binding import (
    handle_project_github_binding_bind,
)
from yoke_core.domain.project_github_binding import (
    cmd_bind_project_repo,
    cmd_project_github_binding_status,
    cmd_unbind_project_repo,
    normalize_github_repo,
)
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_core.domain.yoke_function_permissions import DispatchPermission
from yoke_core.domain.yoke_function_registry import reset_registry_for_tests


def _verified(
    *,
    permissions=None,
    github_repo="Example-Org/Buzz",
    installation_status="active",
) -> VerifiedProjectGitHubBinding:
    return VerifiedProjectGitHubBinding(
        installation_id="12345",
        account_id="9988",
        account_login="Example-Org",
        account_type="Organization",
        repository_selection="selected",
        permissions=permissions or {
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
        github_repo=github_repo,
        default_branch="trunk",
        installation_status=installation_status,
    )


def test_bind_status_and_unbind_round_trip(monkeypatch):
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
        status = cmd_bind_project_repo(
            "buzz",
            installation_id="12345",
            github_repo="git@github.com:Example-Org/Buzz.git",
            repository_id="4567",
            expected_api_url="https://api.github.com",
            github_user_access_token="github-user-token",
            verifier=lambda **kwargs: _verified(),
        )

        assert status["bound"] is True
        assert status["github_repo"] == "Example-Org/Buzz"
        assert status["default_branch"] == "trunk"
        assert status["binding"]["api_url"] == "https://api.github.com"
        assert status["installation"]["api_url"] == "https://api.github.com"
        assert status["automation"] == {"available": True, "reason": "bound"}
        assert status["permission_status"] == {
            "status": "satisfied",
            "missing": [],
        }

        conn = pg_testdb.connect_test_database(db_name)
        try:
            project = conn.execute(
                "SELECT github_repo, default_branch FROM projects "
                "WHERE slug=%s",
                ("buzz",),
            ).fetchone()
            assert project["github_repo"] == "Example-Org/Buzz"
            assert project["default_branch"] == "trunk"
        finally:
            conn.close()

        unbound = cmd_unbind_project_repo("buzz")
        assert unbound["bound"] is False
        assert unbound["automation"] == {
            "available": False,
            "reason": "repo_not_bound",
        }
        assert unbound["github_sync_mode"] == "backlog_only"
    finally:
        pg_testdb.drop_test_database(db_name)
def test_status_reports_missing_permissions(monkeypatch):
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

        cmd_bind_project_repo(
            "buzz",
            installation_id="12345",
            github_repo="example-org/buzz",
            repository_id="4567",
            expected_api_url="https://api.github.com",
            github_user_access_token="github-user-token",
            verifier=lambda **kwargs: _verified(
                permissions={"metadata": "read", "issues": "read"},
                github_repo="example-org/buzz",
            ),
        )

        status = cmd_project_github_binding_status("buzz")

        assert status["permission_status"]["status"] == "missing"
        assert "issues" in status["permission_status"]["missing"]
        assert "contents" in status["permission_status"]["missing"]
        assert "Grant the GitHub App" in status["permission_status"]["hint"]
        assert status["binding"]["status"] == "pending"
        assert status["github_sync_mode"] == "enabled"
        assert status["automation"] == {
            "available": False,
            "reason": "missing_permissions",
        }

        promoted = cmd_bind_project_repo(
            "buzz",
            installation_id="12345",
            github_repo="example-org/buzz",
            repository_id="4567",
            expected_api_url="https://api.github.com",
            github_user_access_token="github-user-token",
            verifier=lambda **kwargs: _verified(github_repo="example-org/buzz"),
        )

        assert promoted["binding"]["status"] == "active"
        assert promoted["permission_status"]["status"] == "satisfied"
        assert promoted["github_sync_mode"] == "enabled"
        assert promoted["automation"] == {"available": True, "reason": "bound"}
    finally:
        pg_testdb.drop_test_database(db_name)


def test_suspended_installation_persists_unavailable_binding(monkeypatch):
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

        status = cmd_bind_project_repo(
            "buzz",
            installation_id="12345",
            github_repo="example-org/buzz",
            repository_id="4567",
            expected_api_url="https://api.github.com",
            github_user_access_token="github-user-token",
            verifier=lambda **kwargs: _verified(
                github_repo="example-org/buzz",
                installation_status="suspended",
            ),
        )

        assert status["installation"]["status"] == "suspended"
        assert status["binding"]["status"] == "unavailable"
        assert status["github_sync_mode"] == "enabled"
        assert status["automation"] == {
            "available": False,
            "reason": "installation_suspended",
        }
    finally:
        pg_testdb.drop_test_database(db_name)


def test_bind_preserves_intentional_backlog_only(monkeypatch):
    db_name = pg_testdb.create_test_database()
    try:
        conn = pg_testdb.connect_test_database(db_name)
        try:
            apply_fixture_schema(conn)
            conn.execute(
                "UPDATE projects SET github_sync_mode='backlog_only' "
                "WHERE slug='buzz'"
            )
            conn.commit()
        finally:
            conn.close()
        monkeypatch.setenv(
            db_backend.PG_DSN_ENV,
            pg_testdb.dsn_for_test_database(db_name),
        )

        status = cmd_bind_project_repo(
            "buzz",
            installation_id="12345",
            github_repo="example-org/buzz",
            repository_id="4567",
            expected_api_url="https://api.github.com",
            github_user_access_token="github-user-token",
            verifier=lambda **kwargs: _verified(github_repo="example-org/buzz"),
        )

        assert status["bound"] is True
        assert status["binding"]["status"] == "active"
        assert status["github_sync_mode"] == "backlog_only"
        assert status["automation"] == {"available": True, "reason": "bound"}
    finally:
        pg_testdb.drop_test_database(db_name)


def test_registered_dispatcher_bind_surface(monkeypatch):
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
        reset_registry_for_tests()
        register_all_handlers()
        monkeypatch.setattr(
            binding_domain,
            "verify_project_github_binding",
            lambda **kwargs: _verified(github_repo="example-org/buzz"),
        )

        with mock.patch(
            "yoke_core.domain.yoke_function_dispatch."
            "dispatch_permission_for_request",
            return_value=DispatchPermission(
                "projects.admin", 2, "buzz",
            ),
        ):
            response = dispatch(
                FunctionCallRequest(
                    function="projects.github_binding.bind",
                    target=TargetRef(kind="global"),
                    actor=ActorContext(actor_id="1", session_id="test-session"),
                    payload={
                            "project": "buzz",
                            "installation_id": "12345",
                            "repository_id": "4567",
                            "github_repo": "example-org/buzz",
                            "expected_api_url": "https://api.github.com",
                            "github_user_access_token": "github-user-token",
                    },
                )
            )

        assert response.success is True
        assert response.result["bound"] is True
        assert response.result["binding"]["installation_id"] == "12345"
    finally:
        reset_registry_for_tests()
        pg_testdb.drop_test_database(db_name)


def test_bind_validation_never_reflects_transient_user_token():
    outcome = handle_project_github_binding_bind(FunctionCallRequest(
        function="projects.github_binding.bind",
        target=TargetRef(kind="global"),
        actor=ActorContext(actor_id="1", session_id="test-session"),
        payload={
            "project": "buzz",
            "installation_id": "12345",
            "github_repo": "example-org/buzz",
            "expected_api_url": "https://api.github.com",
            "github_user_access_token": "github-user-token-must-stay-secret",
            "account_id": "caller-metadata-is-forbidden",
        },
    ))

    assert outcome.primary_success is False
    assert outcome.error.code == "payload_invalid"
    assert "github-user-token-must-stay-secret" not in outcome.error.message
    assert "repository_id" in outcome.error.message
    assert "account_id" in outcome.error.message


def test_repo_normalization_accepts_common_clone_urls():
    assert normalize_github_repo("git@github.com:Example-Org/Buzz.git") == (
        "example-org/buzz"
    )
    assert normalize_github_repo("https://github.com/Example-Org/Buzz.git") == (
        "example-org/buzz"
    )
    assert normalize_github_repo("example-org/buzz") == "example-org/buzz"
    assert normalize_github_repo("missing-owner") == ""
    assert normalize_github_repo(
        "https://github.enterprise.example/Example-Org/Buzz.git"
    ) == "example-org/buzz"
    assert normalize_github_repo(
        "git@github.enterprise.example:Example-Org/Buzz.git"
    ) == "example-org/buzz"
    assert normalize_github_repo(
        "ssh://git@github.enterprise.example/Example-Org/Buzz.git"
    ) == "example-org/buzz"


@pytest.mark.parametrize(
    "value",
    [
        "https://github.enterprise.example/team/owner/repo",
        "https://user:secret@github.enterprise.example/owner/repo",
        "https://github.enterprise.example/owner/repo?redirect=bad",
        "ssh://git@github.enterprise.example/owner/repo/extra",
        "owner/repo/extra",
        "../owner/repo",
    ],
)
def test_repo_normalization_rejects_malformed_extra_path_urls(value):
    assert normalize_github_repo(value) == ""
