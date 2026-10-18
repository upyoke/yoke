"""Stored recipient ownership and the policy that owner supplies."""

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.session_message_authorization import (
    MessageScopePolicy,
    scope_policy,
)
from yoke_core.domain.session_scope_identity import session_scope_of


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
