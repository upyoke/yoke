"""The launch decisions one actor holds on one project.

A launch is authorized by what its actor may do on the project: operating it
(writing items) lets the actor launch, and administering it widens which
machines the actor may place a launch on. Every launch surface — the
registered launch functions and the steering report's level dry run — reads
those decisions here, so a report never shows a placement its reader could
not launch.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.session_launch_types import LaunchAuthorization


def launch_authorization(
    conn: Any, *, actor_id: int, project_id: int, session_id: str | None
) -> LaunchAuthorization:
    """Resolve ``actor_id``'s launch permissions on ``project_id``."""
    from yoke_core.domain.actor_permissions import (
        PERM_ITEMS_WRITE,
        PERM_PROJECT_ADMIN,
        permission_decision,
    )

    def allowed(permission_key: str) -> bool:
        return permission_decision(
            conn,
            actor_id=int(actor_id),
            project_id=int(project_id),
            permission_key=permission_key,
        ).allowed

    return LaunchAuthorization(
        actor_id=int(actor_id),
        session_id=session_id,
        can_operate_project=allowed(PERM_ITEMS_WRITE),
        can_administer_project=allowed(PERM_PROJECT_ADMIN),
    )


__all__ = ["launch_authorization"]
