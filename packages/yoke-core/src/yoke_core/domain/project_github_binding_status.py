"""Read the verified GitHub binding and automation status for one project."""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.project_contract.github_sync_mode import GITHUB_SYNC_DISABLED

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect, query_one
from yoke_core.domain.project_github_binding_payload import (
    automation_status,
    binding_payload,
    installation_payload,
    permission_status,
)
from yoke_core.domain.project_identity import resolve_project


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def cmd_project_github_binding_status(
    project: str,
    *,
    db_path: Optional[str] = None,
    conn: Optional[Any] = None,
) -> dict[str, Any]:
    """Return repository binding and automation availability for a project."""
    owns_conn = conn is None
    if owns_conn:
        conn = connect(db_path)
    try:
        assert conn is not None
        ident = resolve_project(conn, project, required=True)
        assert ident is not None
        placeholder = _placeholder(conn)
        project_row = query_one(
            conn,
            f"SELECT slug, github_repo, default_branch, github_sync_mode "
            f"FROM projects WHERE id={placeholder}",
            (ident.id,),
        )
        binding = query_one(
            conn,
            f"SELECT * FROM project_github_repo_bindings WHERE project_id={placeholder}",
            (ident.id,),
        )
        installation = None
        if binding is not None:
            installation = query_one(
                conn,
                f"SELECT * FROM github_app_installations WHERE installation_id={placeholder}",
                (binding["installation_id"],),
            )
        binding_info = binding_payload(binding)
        installation_info = installation_payload(installation)
        permissions_info = permission_status(
            installation_info.get("permissions", {}) if installation_info else {}
        )
        return {
            "project": ident.slug,
            "github_repo": str(project_row["github_repo"] or "") if project_row else "",
            "default_branch": (
                str(project_row["default_branch"] or "") if project_row else ""
            ),
            "github_sync_mode": (
                str(project_row["github_sync_mode"] or GITHUB_SYNC_DISABLED)
                if project_row
                else GITHUB_SYNC_DISABLED
            ),
            "bound": binding_info is not None,
            "binding": binding_info,
            "installation": installation_info,
            "permission_status": permissions_info,
            "automation": automation_status(
                binding_info,
                installation_info,
                permissions_info,
            ),
        }
    finally:
        if owns_conn and conn is not None:
            conn.close()
