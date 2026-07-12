"""Trusted hosted lifecycle updates for GitHub App project bindings."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_core.domain.db_helpers import connect, iso8601_now, query_one
from yoke_core.domain.project_github_binding_payload import (
    permission_status,
    permissions_dict,
    permissions_text,
)
from yoke_core.domain.project_github_binding_state import (
    BINDING_ACTIVE,
    BINDING_UNAVAILABLE,
    INSTALLATION_ACTIVE,
    INSTALLATION_DELETED,
    INSTALLATION_STATUS_VALUES,
    BindingPersistenceState,
    binding_persistence_state,
    refresh_project_binding,
)
from yoke_core.domain.project_identity import resolve_project


class ProjectGithubBindingLifecycleError(ValueError):
    """A lifecycle delivery does not match the project's verified binding."""


def cmd_apply_project_github_binding_lifecycle(
    project: str,
    *,
    installation_id: str,
    repository_id: str,
    installation_status: str,
    repository_available: bool,
    permissions: Mapping[str, Any] | None = None,
    db_path: Optional[str] = None,
    conn: Optional[Any] = None,
) -> dict[str, Any]:
    """Apply one signature-verified hosted installation/repository event."""
    installation_key = str(installation_id or "").strip()
    if not installation_key.isdigit() or int(installation_key) <= 0:
        raise ProjectGithubBindingLifecycleError(
            "installation_id must be a positive GitHub identifier"
        )
    repository_key = str(repository_id or "").strip()
    if not repository_key.isdigit() or int(repository_key) <= 0:
        raise ProjectGithubBindingLifecycleError(
            "repository_id must be a positive GitHub identifier"
        )
    status = str(installation_status or "").strip()
    if status not in INSTALLATION_STATUS_VALUES:
        raise ProjectGithubBindingLifecycleError(
            "installation_status must be active, pending, suspended, or deleted"
        )
    owns_conn = conn is None
    if owns_conn:
        conn = connect(db_path)
    try:
        assert conn is not None
        ident = resolve_project(conn, project, required=True)
        assert ident is not None
        installation = query_one(
            conn,
            "SELECT permissions, status FROM github_app_installations "
            "WHERE installation_id=%s FOR UPDATE",
            (installation_key,),
        )
        if installation is None:
            raise ProjectGithubBindingLifecycleError(
                "bound GitHub App installation is unavailable"
            )
        binding = query_one(
            conn,
            "SELECT installation_id, repository_id "
            "FROM project_github_repo_bindings "
            "WHERE project_id=%s FOR UPDATE",
            (ident.id,),
        )
        if binding is None:
            raise ProjectGithubBindingLifecycleError(
                "project has no GitHub App repository binding"
            )
        if (
            str(binding["installation_id"]) != installation_key
            or str(binding["repository_id"]) != repository_key
        ):
            raise ProjectGithubBindingLifecycleError(
                "lifecycle installation/repository does not match the project binding"
            )
        stored_status = str(installation["status"] or "")
        deleted_is_terminal = (
            stored_status == INSTALLATION_DELETED
            and status != INSTALLATION_DELETED
        )
        effective_status = INSTALLATION_DELETED if deleted_is_terminal else status
        selected_permissions = (
            permissions_text(permissions)
            if permissions is not None and not deleted_is_terminal
            else permissions_text(permissions_dict(installation["permissions"]))
        )
        permission_state = permission_status(
            permissions_dict(selected_permissions)
        )
        persistence = binding_persistence_state(
            effective_status,
            str(permission_state.get("status") or "unknown"),
        )
        now = iso8601_now()
        if not deleted_is_terminal:
            conn.execute(
                "UPDATE github_app_installations SET permissions=%s, status=%s, "
                "last_verified_at=%s, last_error=%s, updated_at=%s "
                "WHERE installation_id=%s",
                (
                    selected_permissions,
                    effective_status,
                    now,
                    persistence.installation_error,
                    now,
                    installation_key,
                ),
            )
        target_persistence = persistence
        if (
            not repository_available
            and effective_status == INSTALLATION_ACTIVE
            and persistence.binding_status == BINDING_ACTIVE
        ):
            target_persistence = BindingPersistenceState(
                BINDING_UNAVAILABLE,
                persistence.installation_error,
                "repository_unavailable",
            )
        refresh_project_binding(
            conn,
            project_id=ident.id,
            permissions=selected_permissions,
            persistence=target_persistence,
            verified_at=now,
        )
        if owns_conn:
            conn.commit()
        from yoke_core.domain.project_github_binding import (
            cmd_project_github_binding_status,
        )

        return cmd_project_github_binding_status(project, conn=conn)
    finally:
        if owns_conn and conn is not None:
            conn.close()


__all__ = [
    "ProjectGithubBindingLifecycleError",
    "cmd_apply_project_github_binding_lifecycle",
]
