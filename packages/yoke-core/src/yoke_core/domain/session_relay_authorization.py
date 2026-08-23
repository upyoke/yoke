"""Project authorization boundary for relay advertisements."""

from __future__ import annotations

from typing import Any, Iterable

from yoke_core.domain.actor_permissions import PERM_ITEMS_WRITE, permission_decision
from yoke_core.domain.session_relay_types import SessionRelayError


def require_relay_project_authority(
    conn: Any,
    *,
    actor_id: int,
    project_ids: Iterable[int],
) -> None:
    """Refuse a heartbeat before it advertises any unauthorized project."""
    requested = tuple(sorted({int(project_id) for project_id in project_ids}))
    denied = tuple(
        project_id
        for project_id in requested
        if not permission_decision(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            permission_key=PERM_ITEMS_WRITE,
        ).allowed
    )
    if denied:
        raise SessionRelayError(
            "permission_denied",
            f"actor {actor_id} cannot operate advertised projects: "
            + ", ".join(str(project_id) for project_id in denied),
        )


__all__ = ["require_relay_project_authority"]
