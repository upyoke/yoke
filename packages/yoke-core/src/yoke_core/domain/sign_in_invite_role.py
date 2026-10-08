"""The org role an invite grants when sign-in accepts it.

Sign-in checks the role before it creates, links, or accepts anything, so an
invite whose role cannot be granted is refused by name and leaves no partial
admission behind.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.actor_invites import Invite
from yoke_core.domain.actor_permissions import grant_actor_org_role
from yoke_core.domain.actor_role import (
    ActorRoleRefused,
    check_person_role_change,
    require_human_org_role,
)


def _invite_role(conn: Any, invite: Invite) -> Optional[str]:
    if invite.role_id is None:
        return None
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT name FROM roles WHERE id = {p}",
        (invite.role_id,),
    ).fetchone()
    if row is None:
        raise LookupError(
            f"invite {invite.invite_id} names role id {invite.role_id}, which "
            "is not in the role catalog; revoke the invite and invite again"
        )
    return str(row[0])


def invite_role_refusal(conn: Any, invite: Invite) -> Optional[str]:
    """Return why the invite's role cannot be granted, with the recovery, or None."""
    role = _invite_role(conn, invite)
    if role is None:
        return None
    try:
        if invite.actor_id is None:
            require_human_org_role(role)
        else:
            check_person_role_change(
                conn, actor_id=invite.actor_id, org_id=invite.org_id, role=role
            )
    except ActorRoleRefused as exc:
        return (
            f"invite {invite.invite_id} cannot be accepted: {exc}. Ask an org "
            f"admin to run `yoke identity invite revoke {invite.invite_id}` and "
            "invite again with a role it can grant"
        )
    return None


def grant_invite_role(conn: Any, invite: Invite, actor_id: int) -> None:
    role = _invite_role(conn, invite)
    if role is not None:
        grant_actor_org_role(
            conn,
            actor_id=actor_id,
            org_id=invite.org_id,
            role_name=role,
            granted_by_actor_id=invite.invited_by_actor_id,
        )
