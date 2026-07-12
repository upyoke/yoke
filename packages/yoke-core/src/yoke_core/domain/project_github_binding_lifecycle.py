"""Signature-verified GitHub App lifecycle updates for project bindings."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.db_helpers import connect, iso8601_now, query_one
from yoke_core.domain.project_github_binding import (
    ProjectGithubBindingError,
    cmd_project_github_binding_status,
)
from yoke_core.domain.project_github_binding_payload import (
    permission_status,
    permissions_dict,
    permissions_text,
)
from yoke_core.domain.project_github_binding_state import (
    BINDING_UNAVAILABLE,
    INSTALLATION_STATUS_VALUES,
    binding_persistence_state,
    refresh_attached_project_bindings,
)
from yoke_core.domain.project_identity import resolve_project


def _placeholder(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def cmd_update_project_github_binding_lifecycle(
    project: str,
    *,
    installation_id: str,
    installation_status: str,
    repository_available: bool,
    permissions: Optional[dict[str, Any]] = None,
    db_path: Optional[str] = None,
    conn: Optional[Any] = None,
) -> dict[str, Any]:
    """Apply a signature-verified installation or repository lifecycle event."""
    if installation_status not in INSTALLATION_STATUS_VALUES:
        raise ProjectGithubBindingError("invalid installation status")
    owns_conn = conn is None
    if owns_conn:
        conn = connect(db_path)
    try:
        assert conn is not None
        ident = resolve_project(conn, project, required=True)
        assert ident is not None
        placeholder = _placeholder(conn)
        binding = query_one(
            conn,
            "SELECT * FROM project_github_repo_bindings "
            f"WHERE project_id={placeholder}",
            (ident.id,),
        )
        if binding is None or str(binding["installation_id"]) != installation_id:
            raise ProjectGithubBindingError(
                "project is not bound to the supplied installation"
            )
        installation = query_one(
            conn,
            "SELECT * FROM github_app_installations "
            f"WHERE installation_id={placeholder}",
            (installation_id,),
        )
        if installation is None:
            raise ProjectGithubBindingError("GitHub App installation is missing")
        selected_permissions = permissions_text(
            permissions
            if permissions is not None
            else permissions_dict(installation["permissions"])
        )
        permissions_info = permission_status(permissions_dict(selected_permissions))
        persistence = binding_persistence_state(
            installation_status,
            str(permissions_info.get("status") or "unknown"),
        )
        now = iso8601_now()
        _update_installation(
            conn,
            placeholder=placeholder,
            installation_id=installation_id,
            installation_status=installation_status,
            permissions=selected_permissions,
            last_error=persistence.installation_error,
            updated_at=now,
        )
        refresh_attached_project_bindings(
            conn,
            installation_id=installation_id,
            permissions=selected_permissions,
            persistence=persistence,
            verified_at=now,
        )
        if not repository_available:
            conn.execute(
                "UPDATE project_github_repo_bindings SET "
                f"status={placeholder}, last_error={placeholder}, "
                f"updated_at={placeholder} WHERE project_id={placeholder}",
                (BINDING_UNAVAILABLE, "repository_unavailable", now, ident.id),
            )
        if owns_conn:
            conn.commit()
        return cmd_project_github_binding_status(project, conn=conn)
    finally:
        if owns_conn and conn is not None:
            conn.close()


def _update_installation(
    conn: Any,
    *,
    placeholder: str,
    installation_id: str,
    installation_status: str,
    permissions: str,
    last_error: str | None,
    updated_at: str,
) -> None:
    conn.execute(
        "UPDATE github_app_installations SET "
        f"permissions={placeholder}, status={placeholder}, "
        f"last_verified_at={placeholder}, last_error={placeholder}, "
        f"updated_at={placeholder} WHERE installation_id={placeholder}",
        (
            permissions,
            installation_status,
            updated_at,
            last_error,
            updated_at,
            installation_id,
        ),
    )


__all__ = ["cmd_update_project_github_binding_lifecycle"]
