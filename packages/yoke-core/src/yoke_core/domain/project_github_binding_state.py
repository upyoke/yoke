"""State transitions for verified GitHub App repository bindings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_core.domain import db_backend, json_helper
from yoke_core.domain.project_github_auth_models import GITHUB_CAPABILITY_TYPE
from yoke_core.domain.project_github_binding_payload import permissions_dict
from yoke_core.domain.project_github_capability_settings import (
    build_github_capability_settings,
)


BINDING_ACTIVE = "active"
BINDING_PENDING = "pending"
BINDING_UNAVAILABLE = "unavailable"
BINDING_STATUS_VALUES = frozenset({
    BINDING_ACTIVE,
    BINDING_PENDING,
    BINDING_UNAVAILABLE,
})

INSTALLATION_ACTIVE = "active"
INSTALLATION_PENDING = "pending"
INSTALLATION_SUSPENDED = "suspended"
INSTALLATION_DELETED = "deleted"
INSTALLATION_STATUS_VALUES = frozenset({
    INSTALLATION_ACTIVE,
    INSTALLATION_PENDING,
    INSTALLATION_SUSPENDED,
    INSTALLATION_DELETED,
})


@dataclass(frozen=True)
class BindingPersistenceState:
    binding_status: str
    sync_mode: str
    installation_error: str | None
    binding_error: str | None


def binding_persistence_state(
    installation_status: str,
    permission_status_value: str,
) -> BindingPersistenceState:
    """Keep automation disabled until installation and permissions are ready."""
    unavailable = installation_status in {
        INSTALLATION_SUSPENDED,
        INSTALLATION_DELETED,
    }
    missing_permissions = permission_status_value != "satisfied"
    if unavailable:
        error = f"installation_{installation_status}"
        return BindingPersistenceState(
            BINDING_UNAVAILABLE, "backlog_only", error, error,
        )
    if installation_status != INSTALLATION_ACTIVE:
        return BindingPersistenceState(
            BINDING_PENDING, "backlog_only", None, "installation_pending",
        )
    if missing_permissions:
        return BindingPersistenceState(
            BINDING_PENDING, "backlog_only", None, "missing_permissions",
        )
    return BindingPersistenceState(BINDING_ACTIVE, "enabled", None, None)


def refresh_attached_project_bindings(
    conn: Any,
    *,
    installation_id: str,
    permissions: str,
    persistence: BindingPersistenceState,
    verified_at: str,
) -> None:
    """Apply one installation refresh to every attached project atomically."""
    placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"
    conn.execute(
        "UPDATE project_github_repo_bindings SET "
        f"permissions={placeholder}, status={placeholder}, "
        f"last_verified_at={placeholder}, last_error={placeholder}, "
        f"updated_at={placeholder} WHERE installation_id={placeholder}",
        (
            permissions,
            persistence.binding_status,
            verified_at,
            persistence.binding_error,
            verified_at,
            installation_id,
        ),
    )
    conn.execute(
        f"UPDATE projects SET github_sync_mode={placeholder} WHERE id IN "
        "(SELECT project_id FROM project_github_repo_bindings "
        f"WHERE installation_id={placeholder})",
        (persistence.sync_mode, installation_id),
    )
    _refresh_attached_project_capabilities(
        conn,
        installation_id=installation_id,
        permissions=permissions,
        verified_at=verified_at,
    )


def _refresh_attached_project_capabilities(
    conn: Any,
    *,
    installation_id: str,
    permissions: str,
    verified_at: str,
) -> None:
    """Rebuild each attached project's binding-owned capability projection."""
    placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"
    bindings = conn.execute(
        "SELECT project_id, installation_id, repository_id, api_url, github_repo "
        "FROM project_github_repo_bindings "
        f"WHERE installation_id={placeholder} ORDER BY project_id",
        (installation_id,),
    ).fetchall()
    selected_permissions = permissions_dict(permissions)
    for binding in bindings:
        project_id = int(binding["project_id"])
        settings = build_github_capability_settings(
            conn,
            project_id,
            github_repo=str(binding["github_repo"]),
            installation_id=str(binding["installation_id"]),
            repository_id=str(binding["repository_id"]),
            api_url=str(binding["api_url"]),
            permissions=selected_permissions,
        )
        conn.execute(
            "INSERT INTO project_capabilities "
            "(project_id, type, settings, created_at) "
            f"VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}) "
            "ON CONFLICT(project_id, type) DO UPDATE SET settings=EXCLUDED.settings",
            (
                project_id,
                GITHUB_CAPABILITY_TYPE,
                json_helper.dumps_compact(settings),
                verified_at,
            ),
        )


__all__ = [
    "BINDING_ACTIVE",
    "BINDING_PENDING",
    "BINDING_STATUS_VALUES",
    "BINDING_UNAVAILABLE",
    "INSTALLATION_ACTIVE",
    "INSTALLATION_DELETED",
    "INSTALLATION_PENDING",
    "INSTALLATION_STATUS_VALUES",
    "INSTALLATION_SUSPENDED",
    "BindingPersistenceState",
    "binding_persistence_state",
    "refresh_attached_project_bindings",
]
