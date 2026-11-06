# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.fixtures.actor_roles import seed_project_role

import pytest

from runtime.api.fixtures import pg_testdb

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.actor_permissions import (
    ROLE_OWNER,
    seed_roles_and_permissions,
)

from yoke_core.domain.api_tokens import bootstrap_hosted_service_token

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
            "statuses": "read",
            "workflows": "write",
            "secrets": "write",
            "actions_variables": "write",
        },
        repository_id=repository_id,
        github_repo=github_repo,
        default_branch="main",
        repository_is_private=True,
        installation_status="active",
    )


def _project_owner_actor(database_name: str, project: str) -> str:
    conn = pg_testdb.connect_test_database(database_name)
    try:
        actor_id = int(
            conn.execute(
                "INSERT INTO actors (kind, created_at) "
                "VALUES ('human', '2026-01-01T00:00:00Z') RETURNING id"
            ).fetchone()[0]
        )
        project_id = resolve_project_id(conn, project)
        seed_project_role(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            role_name=ROLE_OWNER,
            granted_by_actor_id=actor_id,
        )
        return str(actor_id)
    finally:
        conn.close()


@pytest.fixture
def binding_db(monkeypatch):
    with pg_testdb.test_database() as database:
        name = database.info.dbname
        seed_roles_and_permissions(database)
        cmd_bind_project_repo(
            "externalwebapp",
            installation_id="77",
            repository_id="88",
            github_repo="acme/demo",
            expected_api_url="https://api.github.com",
            github_user_access_token="transient-user-token",
            verifier=lambda **_kwargs: _verified(),
        )
        conn = pg_testdb.connect_test_database(name)
        try:
            conn.execute(
                "UPDATE projects SET github_sync_mode=%s WHERE slug=%s",
                ("enabled", "externalwebapp"),
            )
            conn.commit()
        finally:
            conn.close()
        yield name
