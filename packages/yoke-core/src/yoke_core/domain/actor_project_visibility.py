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
    from yoke_core.domain.actor_permissions import permission_decision
    from yoke_core.domain.project_identity import row_value

    rows = conn.execute("SELECT id FROM projects ORDER BY id").fetchall()
    visible: Set[int] = set()
    for row in rows:
        project_id = int(row_value(row, "id", 0))
        decision = permission_decision(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            permission_key=permission_key,
        )
        if decision.allowed:
            visible.add(project_id)
    return visible


__all__ = [
    "actor_project_ids_with_permission",
    "actor_visible_project_ids",
    "numeric_actor_id",
]
