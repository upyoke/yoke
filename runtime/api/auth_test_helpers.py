"""Shared helpers for authenticated FastAPI API tests."""

from __future__ import annotations

from dataclasses import dataclass

from yoke_core.domain import db_backend
from yoke_core.domain.actor_permissions import (
    ROLE_ADMIN,
    ROLE_OWNER,
    grant_actor_org_role,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.api_tokens import CreatedToken, mint_token
from yoke_core.domain.auth_schema import create_auth_tables
from yoke_core.domain.org_schema import seed_default_org
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_identity_tables,
)
from yoke_core.domain.project_identity import resolve_project_id
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from runtime.api.test_dependency_schema import PROJECTS_SCHEMA


@dataclass(frozen=True)
class ApiAuthContext:
    """Real bearer-token material and actor identity for API route tests."""

    actor_id: int
    project_id: int
    org_id: int
    token: CreatedToken

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token.raw_token}"}


def mint_api_auth_context(
    conn,
    *,
    project: str = "yoke",
    token_name: str = "test-api-token",
) -> ApiAuthContext:
    """Seed grants and mint a real API token in the disposable test DB."""
    _ensure_projects_table(conn)
    create_actor_identity_tables(conn)
    create_auth_tables(conn)
    seed_default_org(conn)
    seed_roles_and_permissions(conn)
    actor_id = seed_human_actor(conn)
    project_id = resolve_project_id(conn, project)
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT org_id FROM projects WHERE id = {p}",
        (project_id,),
    ).fetchone()
    org_id = int(row[0]) if row is not None and row[0] is not None else 1
    grant_actor_project_role(
        conn,
        actor_id=actor_id,
        project_id=project_id,
        role_name=ROLE_OWNER,
        granted_by_actor_id=actor_id,
    )
    grant_actor_org_role(
        conn,
        actor_id=actor_id,
        org_id=org_id,
        role_name=ROLE_ADMIN,
        granted_by_actor_id=actor_id,
    )
    token = mint_token(conn, actor_id=actor_id, name=token_name)
    return ApiAuthContext(
        actor_id=actor_id,
        project_id=project_id,
        org_id=org_id,
        token=token,
    )


def _ensure_projects_table(conn) -> None:
    try:
        conn.execute("SELECT 1 FROM projects LIMIT 1").fetchone()
    except db_backend.database_error_types(conn):
        try:
            conn.rollback()
        except Exception:
            pass
        apply_fixture_ddl(conn, PROJECTS_SCHEMA)


__all__ = ["ApiAuthContext", "mint_api_auth_context"]
