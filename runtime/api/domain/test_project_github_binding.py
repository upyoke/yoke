from __future__ import annotations

from unittest import mock

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_schema
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import db_backend
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.project_github_binding import (
    cmd_bind_project_repo,
    cmd_project_github_binding_status,
    cmd_unbind_project_repo,
    normalize_github_repo,
)
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_core.domain.yoke_function_permissions import DispatchPermission
from yoke_core.domain.yoke_function_registry import reset_registry_for_tests


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
            account_id="9988",
            account_login="Example-Org",
            account_type="Organization",
            github_repo="git@github.com:Example-Org/Buzz.git",
            repository_id="4567",
            default_branch="trunk",
            permissions={
                "metadata": "read",
                "issues": "write",
                "pull_requests": "write",
                "contents": "write",
                "actions": "write",
                "workflows": "write",
                "secrets": "write",
                "variables": "write",
            },
        )

        assert status["bound"] is True
        assert status["github_repo"] == "example-org/buzz"
        assert status["default_branch"] == "trunk"
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
            assert project["github_repo"] == "example-org/buzz"
            assert project["default_branch"] == "trunk"
            capability = conn.execute(
                "SELECT settings FROM project_capabilities "
                "WHERE project_id=2 AND type='github'",
            ).fetchone()
            assert "github_app" in capability["settings"]
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
            account_id="9988",
            account_login="example-org",
            account_type="Organization",
            github_repo="example-org/buzz",
            permissions={"metadata": "read", "issues": "read"},
        )

        status = cmd_project_github_binding_status("buzz")

        assert status["permission_status"]["status"] == "missing"
        assert "issues" in status["permission_status"]["missing"]
        assert "contents" in status["permission_status"]["missing"]
        assert status["automation"] == {
            "available": False,
            "reason": "missing_permissions",
        }
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
                        "account_id": "9988",
                        "account_login": "example-org",
                        "account_type": "Organization",
                        "github_repo": "example-org/buzz",
                    },
                )
            )

        assert response.success is True
        assert response.result["bound"] is True
        assert response.result["binding"]["installation_id"] == "12345"
    finally:
        reset_registry_for_tests()
        pg_testdb.drop_test_database(db_name)


def test_repo_normalization_accepts_common_clone_urls():
    assert normalize_github_repo("git@github.com:Example-Org/Buzz.git") == (
        "example-org/buzz"
    )
    assert normalize_github_repo("https://github.com/Example-Org/Buzz.git") == (
        "example-org/buzz"
    )
    assert normalize_github_repo("example-org/buzz") == "example-org/buzz"
    assert normalize_github_repo("missing-owner") == ""
