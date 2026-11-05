# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.domain.yoke_function_permissions_test_support import _entry

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.actor_permissions import (
    ROLE_OWNER,
    grant_actor_project_role,
    seed_roles_and_permissions,
)

from yoke_core.domain.function_authz_scope import PROJECT, classify

from yoke_core.domain.ouroboros_entries import cmd_insert_entry

from yoke_core.domain.ouroboros_entry_review import MAX_ENTRY_REVIEW_BATCH

from yoke_core.domain.project_identity import resolve_project_id

from yoke_core.domain.yoke_function_permissions import (
    check_dispatch_permission,
    permission_key_for,
)


def _project_owner(conn, project_slug: str) -> int:
    seed_roles_and_permissions(conn)
    actor_id = int(
        conn.execute(
            "INSERT INTO actors (kind, created_at) "
            "VALUES ('human', '2026-01-01T00:00:00Z') RETURNING id"
        ).fetchone()[0]
    )
    grant_actor_project_role(
        conn,
        actor_id=actor_id,
        project_id=resolve_project_id(conn, project_slug),
        role_name=ROLE_OWNER,
        granted_by_actor_id=actor_id,
    )
    conn.commit()
    return actor_id
