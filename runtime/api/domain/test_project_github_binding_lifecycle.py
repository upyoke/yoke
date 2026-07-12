"""Hosted GitHub installation and repository lifecycle delivery tests."""

from __future__ import annotations

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_schema
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import db_backend
from yoke_core.domain.actor_permissions import (
    ROLE_OWNER,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.github_app_user_verification import (
    VerifiedProjectGitHubBinding,
)
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.project_github_binding import cmd_bind_project_repo
from yoke_core.domain.project_github_binding_lifecycle import (
    ProjectGithubBindingLifecycleError,
    cmd_apply_project_github_binding_lifecycle,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_core.domain.yoke_function_registry import reset_registry_for_tests


def _verified(
    *,
    repository_id: str = "88",
    github_repo: str = "acme/demo",
) -> VerifiedProjectGitHubBinding:
    return VerifiedProjectGitHubBinding(
        installation_id="77",
        account_id="10",
        account_login="acme",
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


@pytest.fixture
def binding_db(monkeypatch):
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    try:
        apply_fixture_schema(conn)
        seed_roles_and_permissions(conn)
    finally:
        conn.close()
    monkeypatch.setenv(db_backend.PG_DSN_ENV, pg_testdb.dsn_for_test_database(name))
    cmd_bind_project_repo(
        "buzz",
        installation_id="77",
        repository_id="88",
        github_repo="acme/demo",
        expected_api_url="https://api.github.com",
        github_user_access_token="transient-user-token",
        verifier=lambda **_kwargs: _verified(),
    )
    try:
        yield name
    finally:
        pg_testdb.drop_test_database(name)


def _project_owner_actor(database_name: str, project: str) -> str:
    conn = pg_testdb.connect_test_database(database_name)
    try:
        actor_id = int(conn.execute(
            "INSERT INTO actors (kind, created_at) "
            "VALUES ('human', '2026-01-01T00:00:00Z') RETURNING id"
        ).fetchone()[0])
        project_id = resolve_project_id(conn, project)
        grant_actor_project_role(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            role_name=ROLE_OWNER,
            granted_by_actor_id=actor_id,
        )
        return str(actor_id)
    finally:
        conn.close()


def test_lifecycle_suspends_and_restores_bound_project(binding_db) -> None:
    suspended = cmd_apply_project_github_binding_lifecycle(
        "buzz",
        installation_id="77",
        repository_id="88",
        installation_status="suspended",
        repository_available=True,
    )

    assert suspended["installation"]["status"] == "suspended"
    assert suspended["binding"]["status"] == "unavailable"
    assert suspended["automation"] == {
        "available": False,
        "reason": "installation_suspended",
    }
    assert suspended["github_sync_mode"] == "enabled"

    restored = cmd_apply_project_github_binding_lifecycle(
        "buzz",
        installation_id="77",
        repository_id="88",
        installation_status="active",
        repository_available=True,
        permissions=_verified().permissions,
    )

    assert restored["binding"]["status"] == "active"
    assert restored["automation"] == {"available": True, "reason": "bound"}
    assert restored["github_sync_mode"] == "enabled"


def test_lifecycle_marks_removed_repository_unavailable(binding_db) -> None:
    result = cmd_apply_project_github_binding_lifecycle(
        "buzz",
        installation_id="77",
        repository_id="88",
        installation_status="active",
        repository_available=False,
    )

    assert result["installation"]["status"] == "active"
    assert result["binding"]["status"] == "unavailable"
    assert result["binding"]["last_error"] == "repository_unavailable"
    assert result["automation"] == {
        "available": False,
        "reason": "binding_unavailable",
    }


def test_lifecycle_rejects_foreign_installation_without_mutation(binding_db) -> None:
    with pytest.raises(
        ProjectGithubBindingLifecycleError,
        match="unavailable|does not match",
    ):
        cmd_apply_project_github_binding_lifecycle(
            "buzz",
            installation_id="999",
            repository_id="88",
            installation_status="deleted",
            repository_available=False,
        )
    conn = pg_testdb.connect_test_database(binding_db)
    try:
        row = conn.execute(
            "SELECT status FROM project_github_repo_bindings WHERE project_id=2"
        ).fetchone()
        assert row["status"] == "active"
    finally:
        conn.close()


def test_lifecycle_rejects_stale_repository_without_mutation(binding_db) -> None:
    with pytest.raises(
        ProjectGithubBindingLifecycleError,
        match="does not match",
    ):
        cmd_apply_project_github_binding_lifecycle(
            "buzz",
            installation_id="77",
            repository_id="999",
            installation_status="deleted",
            repository_available=False,
        )
    conn = pg_testdb.connect_test_database(binding_db)
    try:
        row = conn.execute(
            "SELECT status FROM project_github_repo_bindings WHERE project_id=2"
        ).fetchone()
        assert row["status"] == "active"
    finally:
        conn.close()


@pytest.mark.parametrize(
    "delivery_order",
    [("removed", "available"), ("available", "removed")],
)
def test_repository_availability_is_target_scoped_and_order_independent(
    binding_db,
    delivery_order,
) -> None:
    cmd_bind_project_repo(
        "yoke",
        installation_id="77",
        repository_id="99",
        github_repo="acme/other",
        expected_api_url="https://api.github.com",
        github_user_access_token="transient-user-token",
        verifier=lambda **_kwargs: _verified(
            repository_id="99",
            github_repo="acme/other",
        ),
    )
    deliveries = {
        "removed": ("buzz", "88", False),
        "available": ("yoke", "99", True),
    }
    for delivery in delivery_order:
        project, repository_id, available = deliveries[delivery]
        cmd_apply_project_github_binding_lifecycle(
            project,
            installation_id="77",
            repository_id=repository_id,
            installation_status="active",
            repository_available=available,
        )

    conn = pg_testdb.connect_test_database(binding_db)
    try:
        rows = conn.execute(
            "SELECT project_id, status, last_error "
            "FROM project_github_repo_bindings ORDER BY project_id"
        ).fetchall()
        assert [(row["project_id"], row["status"], row["last_error"]) for row in rows] == [
            (1, "active", None),
            (2, "unavailable", "repository_unavailable"),
        ]
    finally:
        conn.close()


def test_deleted_installation_cannot_be_reactivated_by_delayed_event(
    binding_db,
) -> None:
    cmd_apply_project_github_binding_lifecycle(
        "buzz",
        installation_id="77",
        repository_id="88",
        installation_status="deleted",
        repository_available=False,
    )
    result = cmd_apply_project_github_binding_lifecycle(
        "buzz",
        installation_id="77",
        repository_id="88",
        installation_status="active",
        repository_available=True,
    )

    assert result["installation"]["status"] == "deleted"
    assert result["binding"]["status"] == "unavailable"
    assert result["automation"]["reason"] == "installation_deleted"


def test_registered_lifecycle_dispatch_reaches_real_domain(binding_db) -> None:
    actor_id = _project_owner_actor(binding_db, "yoke")
    reset_registry_for_tests()
    register_all_handlers()
    try:
        response = dispatch(FunctionCallRequest(
            function="projects.github_binding.lifecycle",
            target=TargetRef(kind="global"),
            actor=ActorContext(
                actor_id=actor_id,
                session_id="hosted-webhook",
            ),
            payload={
                "project": "2",
                "installation_id": "77",
                "repository_id": "88",
                "installation_status": "deleted",
                "repository_available": False,
            },
        ))
        assert response.success is True
        assert response.result["installation"]["status"] == "deleted"
        assert response.result["automation"]["reason"] == "installation_deleted"
    finally:
        reset_registry_for_tests()
