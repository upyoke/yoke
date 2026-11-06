"""Serialize stored email invites with recorded roles and inviter names."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any
from yoke_contracts.timestamps import temporal_wire
from yoke_core.domain import db_backend
from yoke_core.domain.actor_invites import Invite


def serialize_invites(conn: Any, invites: list[Invite]) -> list[dict]:
    """Retain invite fields and resolve recorded role and inviter names in bulk."""
    if not invites:
        return []
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    ids = [invite.invite_id for invite in invites]
    rows = conn.execute(
        "SELECT i.id, r.name, a.name FROM actor_invites i "
        "LEFT JOIN roles r ON r.id = i.role_id "
        "LEFT JOIN actors a ON a.id = i.invited_by_actor_id "
        f"WHERE i.id IN ({','.join([p] * len(ids))})",
        tuple(ids),
    ).fetchall()
    names = {row[0]: (row[1], (row[2] or "").strip() or None) for row in rows}
    return [
        temporal_wire(
            dict(
                asdict(invite),
                role=names[invite.invite_id][0],
                invited_by_name=names[invite.invite_id][1],
            )
        )
        for invite in invites
    ]
