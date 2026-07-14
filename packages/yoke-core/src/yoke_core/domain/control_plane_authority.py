"""Organization authority for whole-universe control-plane operations.

A Yoke universe is one organization containing zero or more projects.  Whole-
universe operations therefore belong to that organization, never to a project
whose slug happens to be ``yoke``.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.actor_permissions import (
    PermissionDecision,
    PermissionDenied,
    require_org_permission,
)


def resolve_control_plane_org_id(conn: Any) -> int:
    """Return the universe's sole organization or deny ambiguous authority."""
    rows = conn.execute(
        "SELECT id FROM organizations ORDER BY id LIMIT 2"
    ).fetchall()
    if len(rows) != 1:
        raise PermissionDenied(
            "whole-universe control-plane operations require exactly one "
            f"organization; found {len(rows)}"
        )
    return int(rows[0][0])


def require_control_plane_permission(
    conn: Any,
    *,
    actor_id: int,
    permission_key: str,
) -> PermissionDecision:
    """Require an org grant for a whole-universe operation."""
    return require_org_permission(
        conn,
        actor_id=actor_id,
        org_id=resolve_control_plane_org_id(conn),
        permission_key=permission_key,
    )


__all__ = ["require_control_plane_permission", "resolve_control_plane_org_id"]
