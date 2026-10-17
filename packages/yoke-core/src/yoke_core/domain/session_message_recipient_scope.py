"""Stored recipient ownership, policy lookup and actor read permission."""

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.actor_permissions import PERM_ITEMS_READ
from yoke_core.domain.session_message_authorization import (
    MessageScopePolicy,
    can_read_project,
    scope_policy,
)
from yoke_core.domain.session_scope_identity import (
    actor_may_operate_session,
    session_scope_of,
)


def recipient_owner(session_row: Mapping[str, Any]) -> tuple[int | None, int | None]:
    """Return the exclusive project/org pair recorded on the recipient."""
    scope = session_scope_of(session_row)
    return scope.project_id, scope.org_id


def owner_key(row: Mapping[str, Any]) -> tuple[str, int]:
    """Keep project and org identifiers distinct in policy caches."""
    project_id, org_id = recipient_owner(row)
    return (
        ("project", int(project_id)) if project_id is not None else ("org", int(org_id))
    )


def recipient_policy(conn: Any, row: Mapping[str, Any]) -> MessageScopePolicy:
    project_id, org_id = recipient_owner(row)
    return scope_policy(conn, project_id=project_id, org_id=org_id)


def actor_reads_recipient(conn: Any, *, actor_id: int, row: Mapping[str, Any]) -> bool:
    """Apply target project permission or org ownership/read permission."""
    scope = session_scope_of(row)
    if scope.project_id is not None:
        return can_read_project(conn, actor_id=actor_id, project_id=scope.project_id)
    return actor_may_operate_session(
        conn,
        actor_id=actor_id,
        scope=scope,
        session_actor_id=dict(row).get("actor_id"),
        permission_key=PERM_ITEMS_READ,
    )
