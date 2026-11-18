"""Actor-visible project helpers for authenticated aggregate reads."""

from __future__ import annotations

from typing import Any, Optional, Set


def numeric_actor_id(value: Any) -> Optional[int]:
    """Return the verified numeric actor id, or ``None`` for local context."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or not text.isdigit():
        return None
    return int(text)


def actor_visible_project_ids(
    conn: Any,
    actor_id: Optional[int],
) -> Optional[Set[int]]:
    """Return actor-visible project ids, or ``None`` for local/unscoped calls."""
    if actor_id is None:
        return None
    from yoke_core.domain.actor_state import actor_is_active

    if not actor_is_active(conn, actor_id):
        return set()
    from yoke_core.domain.project_identity import placeholder, row_value

    p = placeholder(conn)
    rows = conn.execute(
        f"SELECT DISTINCT pr.id AS id "
        f"FROM projects pr "
        f"JOIN actor_org_roles aor ON aor.org_id = pr.org_id "
        f"WHERE aor.actor_id = {p} "
        f"UNION "
        f"SELECT DISTINCT apr.project_id AS id "
        f"FROM actor_project_roles apr "
        f"WHERE apr.actor_id = {p}",
        (actor_id, actor_id),
    ).fetchall()
    return {int(row_value(row, "id", 0)) for row in rows}


def actor_project_ids_with_permission(
    conn: Any,
    actor_id: Optional[int],
    permission_key: str,
) -> Optional[Set[int]]:
    """Return project ids where ``actor_id`` has ``permission_key``.

    ``None`` preserves the local/advisory convention used by dispatcher auth:
    without a verified numeric actor, callers own the local instance and reads
    are not project-filtered.
    """
    if actor_id is None:
        return None
    from yoke_core.domain.actor_state import actor_is_active

    if not actor_is_active(conn, actor_id):
        return set()
    return _permitted_project_ids(conn, int(actor_id), permission_key)


def _permitted_project_ids(conn: Any, actor_id: int, permission_key: str) -> Set[int]:
    """:func:`permission_decision`'s four grants, asked of every project at once.

    The same order of authority: an org owner/admin carries every permission
    except service-only ones; a project owner/admin carries every
    project-grantable one; otherwise an org or project role must carry the
    permission explicitly. Asking per project cost one round trip per project
    for each wildcard; every authenticated aggregate read paid it.
    """
    from yoke_core.domain.actor_permissions import (
        ORG_SCOPED_PERMISSIONS,
        ROLE_ADMIN,
        ROLE_OWNER,
        SERVICE_ONLY_PERMISSIONS,
    )
    from yoke_core.domain.project_identity import placeholder, row_value

    p = placeholder(conn)
    org_wildcard = permission_key not in SERVICE_ONLY_PERMISSIONS
    project_grants = permission_key not in ORG_SCOPED_PERMISSIONS
    org_roles = (
        "SELECT pr.id AS id, r.id AS role_id, r.name AS role FROM projects pr "
        "JOIN actor_org_roles aor ON aor.org_id = pr.org_id "
        "JOIN roles r ON r.id = aor.role_id "
        f"WHERE aor.actor_id = {p}"
    )
    project_roles = (
        "SELECT pr.id AS id, r.id AS role_id, r.name AS role "
        "FROM actor_project_roles apr "
        "JOIN projects pr ON pr.id = apr.project_id "
        "JOIN roles r ON r.id = apr.role_id "
        f"WHERE apr.actor_id = {p}"
    )
    carries = (
        "EXISTS (SELECT 1 FROM role_permissions rp "
        "JOIN permissions perm ON perm.id = rp.permission_id "
        f"WHERE rp.role_id = grants.role_id AND perm.key = {p})"
    )
    wildcard = f"grants.role IN ({p}, {p})"
    rows = conn.execute(
        f"SELECT DISTINCT grants.id FROM ({org_roles}) grants "
        f"WHERE ({p} AND {wildcard}) OR {carries} "
        "UNION "
        f"SELECT DISTINCT grants.id FROM ({project_roles}) grants "
        f"WHERE {p} AND ({wildcard} OR {carries})",
        (
            actor_id, org_wildcard, ROLE_ADMIN, ROLE_OWNER, permission_key,
            actor_id, project_grants, ROLE_OWNER, ROLE_ADMIN, permission_key,
        ),
    ).fetchall()
    return {int(row_value(row, "id", 0)) for row in rows}


__all__ = [
    "actor_project_ids_with_permission",
    "actor_visible_project_ids",
    "numeric_actor_id",
]
