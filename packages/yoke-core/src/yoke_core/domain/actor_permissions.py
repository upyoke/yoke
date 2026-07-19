"""Actor/project role grants and permission checks for cloud-runtime auth."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from yoke_core.domain import db_backend


# Project-scoped roles (grantable via ``actor_project_roles``).
ROLE_OWNER = "owner"
ROLE_OPERATOR = "operator"
ROLE_VIEWER = "viewer"
ROLE_DEPLOYMENT_CI = "deployment_ci"
ROLE_INFRASTRUCTURE_CI = "infrastructure_ci"
# Org-scoped role (grantable via ``actor_org_roles``). Renamed from "system":
# the all-access role belongs at org/instance scope, not on a project.
ROLE_ADMIN = "admin"

# Project-scoped permissions.
PERM_ITEMS_READ = "items.read"
PERM_ITEMS_WRITE = "items.write"
PERM_CLAIMS_ACQUIRE = "claims.acquire"
PERM_CLAIMS_RELEASE = "claims.release"
PERM_EVENTS_READ = "events.read"
PERM_EVENTS_WRITE = "events.write"
PERM_HOOKS_EVALUATE = "hooks.evaluate"
PERM_BOARD_REBUILD = "board.rebuild"
PERM_PROJECT_INSTALL = "project.install"
PERM_PROJECT_RENDER_READ = "project.render.read"
PERM_PROJECT_ADMIN = "project.admin"
PERM_DB_READ_RAW = "db.read.raw"
PERM_GITHUB_ACTIONS_WORKFLOW_DISPATCH = "github_actions.workflow.dispatch"
PERM_GITHUB_ACTIONS_RUN_READ = "github_actions.run.read"
PERM_GITHUB_ACTIONS_VARIABLE_READ = "github_actions.variable.read"
PERM_GITHUB_RELEASE_CREATE = "github.release.create"
# Org-scoped permissions (never carried by a project role).
PERM_ORG_ADMIN = "org.admin"  # renamed from "system.admin"
PERM_PROJECT_CREATE = "project.create"

# Permissions that may only be granted at org scope.
ORG_SCOPED_PERMISSIONS = (PERM_ORG_ADMIN, PERM_PROJECT_CREATE)

# Roles grantable at each scope.
ORG_ROLES = (ROLE_ADMIN, ROLE_VIEWER)
PROJECT_ROLES = (
    ROLE_OWNER,
    ROLE_OPERATOR,
    ROLE_VIEWER,
    ROLE_DEPLOYMENT_CI,
    ROLE_INFRASTRUCTURE_CI,
)


ROLE_DESCRIPTIONS = {
    ROLE_OWNER: "Project admin and normal operator work.",
    ROLE_OPERATOR: "Normal Yoke operations for a project.",
    ROLE_VIEWER: "Read-only access.",
    ROLE_DEPLOYMENT_CI: (
        "Create immutable release tags, trigger deployment workflows, and "
        "read their status."
    ),
    ROLE_INFRASTRUCTURE_CI: (
        "Read exact infrastructure render inputs for preview workflows."
    ),
    ROLE_ADMIN: "Org-wide administration across all of the org's projects.",
}

PERMISSION_DESCRIPTIONS = {
    PERM_ITEMS_READ: "Read item data.",
    PERM_ITEMS_WRITE: "Mutate item data.",
    PERM_CLAIMS_ACQUIRE: "Acquire work or path claims.",
    PERM_CLAIMS_RELEASE: "Release work or path claims.",
    PERM_EVENTS_READ: "Read Yoke event telemetry.",
    PERM_EVENTS_WRITE: "Write Yoke event telemetry.",
    PERM_HOOKS_EVALUATE: "Evaluate installed harness hooks.",
    PERM_BOARD_REBUILD: "Render or rebuild board views.",
    PERM_PROJECT_INSTALL: "Install or refresh project-local Yoke files.",
    PERM_PROJECT_RENDER_READ: (
        "Read project settings and encrypted operator state used to render "
        "deployment infrastructure."
    ),
    PERM_PROJECT_ADMIN: "Administer project settings and grants.",
    PERM_DB_READ_RAW: "Run bounded raw diagnostic DB reads.",
    PERM_GITHUB_ACTIONS_WORKFLOW_DISPATCH: (
        "Dispatch a GitHub Actions workflow for the project repository."
    ),
    PERM_GITHUB_ACTIONS_RUN_READ: (
        "Read GitHub Actions workflow and run status for deployment reporting."
    ),
    PERM_GITHUB_ACTIONS_VARIABLE_READ: (
        "Read GitHub Actions variables used to route project deployments."
    ),
    PERM_GITHUB_RELEASE_CREATE: (
        "Create the next immutable annotated release tag for the project."
    ),
    PERM_ORG_ADMIN: "Administer the org and all of its projects.",
    PERM_PROJECT_CREATE: "Create new projects in the org.",
}

# Project-scoped permission set carried by the project ``owner`` role.
_PROJECT_OWNER_PERMS = (
    PERM_ITEMS_READ,
    PERM_ITEMS_WRITE,
    PERM_CLAIMS_ACQUIRE,
    PERM_CLAIMS_RELEASE,
    PERM_EVENTS_READ,
    PERM_EVENTS_WRITE,
    PERM_HOOKS_EVALUATE,
    PERM_BOARD_REBUILD,
    PERM_PROJECT_INSTALL,
    PERM_PROJECT_RENDER_READ,
    PERM_PROJECT_ADMIN,
    PERM_DB_READ_RAW,
    PERM_GITHUB_ACTIONS_WORKFLOW_DISPATCH,
    PERM_GITHUB_ACTIONS_RUN_READ,
    PERM_GITHUB_ACTIONS_VARIABLE_READ,
    PERM_GITHUB_RELEASE_CREATE,
)

ROLE_PERMISSION_KEYS = {
    # Project roles — org-scoped permissions excluded.
    ROLE_OWNER: _PROJECT_OWNER_PERMS,
    ROLE_OPERATOR: (
        PERM_ITEMS_READ,
        PERM_ITEMS_WRITE,
        PERM_CLAIMS_ACQUIRE,
        PERM_CLAIMS_RELEASE,
        PERM_EVENTS_READ,
        PERM_EVENTS_WRITE,
        PERM_HOOKS_EVALUATE,
        PERM_BOARD_REBUILD,
        PERM_PROJECT_INSTALL,
    ),
    ROLE_VIEWER: (PERM_ITEMS_READ, PERM_EVENTS_READ),
    ROLE_DEPLOYMENT_CI: (
        PERM_GITHUB_ACTIONS_WORKFLOW_DISPATCH,
        PERM_GITHUB_ACTIONS_RUN_READ,
        PERM_GITHUB_ACTIONS_VARIABLE_READ,
        PERM_GITHUB_RELEASE_CREATE,
    ),
    ROLE_INFRASTRUCTURE_CI: (
        PERM_PROJECT_RENDER_READ,
    ),
    # Org role — every permission, incl. org-scoped ones.
    ROLE_ADMIN: tuple(PERMISSION_DESCRIPTIONS),
}


class PermissionDenied(PermissionError):
    """Raised when an actor lacks a permission in a project context."""


@dataclass(frozen=True)
class PermissionDecision:
    actor_id: int
    project_id: int | None
    permission_key: str
    allowed: bool
    role_names: tuple[str, ...]
    org_id: int | None = None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def seed_roles_and_permissions(conn: Any) -> None:
    """Seed the v0 allow-only role/permission catalog."""
    p = _p(conn)
    for name, description in ROLE_DESCRIPTIONS.items():
        conn.execute(
            "INSERT INTO roles (name, description, created_at) "
            f"VALUES ({p}, {p}, {p}) "
            "ON CONFLICT(name) DO UPDATE SET description = EXCLUDED.description",
            (name, description, _now()),
        )
    for key, description in PERMISSION_DESCRIPTIONS.items():
        conn.execute(
            "INSERT INTO permissions (key, description, created_at) "
            f"VALUES ({p}, {p}, {p}) "
            "ON CONFLICT(key) DO UPDATE SET description = EXCLUDED.description",
            (key, description, _now()),
        )
    for role_name, permission_keys in ROLE_PERMISSION_KEYS.items():
        role_id = role_id_by_name(conn, role_name)
        permission_ids = tuple(
            permission_id_by_key(conn, key) for key in permission_keys
        )
        placeholders = ", ".join(p for _ in permission_ids)
        conn.execute(
            "DELETE FROM role_permissions "
            f"WHERE role_id = {p} AND permission_id NOT IN ({placeholders})",
            (role_id, *permission_ids),
        )
        for permission_key in permission_keys:
            permission_id = permission_id_by_key(conn, permission_key)
            conn.execute(
                "INSERT INTO role_permissions (role_id, permission_id, created_at) "
                f"VALUES ({p}, {p}, {p}) "
                "ON CONFLICT(role_id, permission_id) DO NOTHING",
                (role_id, permission_id, _now()),
            )
    conn.commit()


def role_id_by_name(conn: Any, role_name: str) -> int:
    p = _p(conn)
    row = conn.execute(
        f"SELECT id FROM roles WHERE name = {p}",
        (role_name,),
    ).fetchone()
    if row is None:
        raise LookupError(f"role {role_name!r} is not seeded")
    return int(row[0])


def permission_id_by_key(conn: Any, permission_key: str) -> int:
    p = _p(conn)
    row = conn.execute(
        f"SELECT id FROM permissions WHERE key = {p}",
        (permission_key,),
    ).fetchone()
    if row is None:
        raise LookupError(f"permission {permission_key!r} is not seeded")
    return int(row[0])


def grant_actor_project_role(
    conn: Any,
    *,
    actor_id: int,
    project_id: int,
    role_name: str,
    granted_by_actor_id: int | None = None,
) -> None:
    """Grant ``role_name`` to ``actor_id`` in ``project_id`` idempotently."""
    role_id = role_id_by_name(conn, role_name)
    p = _p(conn)
    conn.execute(
        "INSERT INTO actor_project_roles "
        "(actor_id, project_id, role_id, granted_at, granted_by_actor_id) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}) "
        "ON CONFLICT(actor_id, project_id, role_id) DO NOTHING",
        (actor_id, project_id, role_id, _now(), granted_by_actor_id),
    )
    conn.commit()


def revoke_actor_project_role(
    conn: Any,
    *,
    actor_id: int,
    project_id: int,
    role_name: str,
) -> bool:
    """Remove one project role grant, returning whether a row existed.

    Absence is success: operators may safely repeat a least-privilege cutover
    after losing the previous command result.
    """
    role_id = role_id_by_name(conn, role_name)
    p = _p(conn)
    cursor = conn.execute(
        "DELETE FROM actor_project_roles "
        f"WHERE actor_id = {p} AND project_id = {p} AND role_id = {p}",
        (actor_id, project_id, role_id),
    )
    conn.commit()
    return bool(cursor.rowcount)


def grant_actor_org_role(
    conn: Any,
    *,
    actor_id: int,
    org_id: int,
    role_name: str,
    granted_by_actor_id: int | None = None,
) -> None:
    """Grant org ``role_name`` to ``actor_id`` in ``org_id`` idempotently."""
    role_id = role_id_by_name(conn, role_name)
    p = _p(conn)
    conn.execute(
        "INSERT INTO actor_org_roles "
        "(actor_id, org_id, role_id, granted_at, granted_by_actor_id) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}) "
        "ON CONFLICT(actor_id, org_id, role_id) DO NOTHING",
        (actor_id, org_id, role_id, _now(), granted_by_actor_id),
    )
    conn.commit()


# Permission/authorization decisions live in the sibling module to keep this
# file under the authored-file line cap; re-exported so callers keep importing
# them from ``yoke_core.domain.actor_permissions``. The import sits below the
# constant/dataclass definitions the checks module pulls back (one-directional;
# nothing imports actor_permission_checks directly).
from yoke_core.domain.actor_permission_checks import (  # noqa: E402
    org_permission_decision,
    permission_decision,
    require_org_permission,
    require_permission,
)


__all__ = [
    "PermissionDecision",
    "PermissionDenied",
    "ROLE_OWNER",
    "ROLE_OPERATOR",
    "ROLE_VIEWER",
    "ROLE_DEPLOYMENT_CI",
    "ROLE_INFRASTRUCTURE_CI",
    "ROLE_ADMIN",
    "ORG_ROLES",
    "PROJECT_ROLES",
    "ORG_SCOPED_PERMISSIONS",
    "PERM_ITEMS_READ",
    "PERM_ITEMS_WRITE",
    "PERM_CLAIMS_ACQUIRE",
    "PERM_CLAIMS_RELEASE",
    "PERM_EVENTS_READ",
    "PERM_EVENTS_WRITE",
    "PERM_HOOKS_EVALUATE",
    "PERM_BOARD_REBUILD",
    "PERM_PROJECT_INSTALL",
    "PERM_PROJECT_RENDER_READ",
    "PERM_PROJECT_ADMIN",
    "PERM_DB_READ_RAW",
    "PERM_GITHUB_ACTIONS_WORKFLOW_DISPATCH",
    "PERM_GITHUB_ACTIONS_RUN_READ",
    "PERM_GITHUB_ACTIONS_VARIABLE_READ",
    "PERM_GITHUB_RELEASE_CREATE",
    "PERM_ORG_ADMIN",
    "PERM_PROJECT_CREATE",
    "grant_actor_org_role",
    "grant_actor_project_role",
    "revoke_actor_project_role",
    "org_permission_decision",
    "permission_decision",
    "permission_id_by_key",
    "require_org_permission",
    "require_permission",
    "role_id_by_name",
    "seed_roles_and_permissions",
]
