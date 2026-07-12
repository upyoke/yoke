"""Usability predicate for verifier-produced project GitHub App bindings."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.project_github_binding_payload import (
    automation_status,
    binding_payload,
    installation_payload,
    permission_status,
)
from yoke_core.domain.schema_common import _table_exists


def project_has_active_verified_github_binding(
    conn: Any,
    project_id: int,
) -> bool:
    """Return whether a project has usable, verifier-produced App binding state."""
    required_tables = (
        "project_capabilities",
        "project_github_repo_bindings",
        "github_app_installations",
    )
    if not all(_table_exists(conn, table) for table in required_tables):
        return False
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    capability = query_one(
        conn,
        f"SELECT 1 FROM project_capabilities WHERE project_id={p} AND type={p}",
        (project_id, "github"),
    )
    binding = query_one(
        conn,
        f"SELECT * FROM project_github_repo_bindings WHERE project_id={p}",
        (project_id,),
    )
    if capability is None or binding is None:
        return False
    installation = query_one(
        conn,
        f"SELECT * FROM github_app_installations WHERE installation_id={p}",
        (binding["installation_id"],),
    )
    if installation is None:
        return False
    binding_info = binding_payload(binding)
    installation_info = installation_payload(installation)
    permissions_info = permission_status(
        installation_info.get("permissions", {}) if installation_info else {},
    )
    automation_info = automation_status(
        binding_info,
        installation_info,
        permissions_info,
    )
    return bool(
        automation_info.get("available")
        and str(binding["last_verified_at"] or "").strip()
        and str(installation["last_verified_at"] or "").strip()
    )


__all__ = ["project_has_active_verified_github_binding"]
