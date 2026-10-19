"""Public invitation rows with stored timestamps and authoritative actor names."""

from __future__ import annotations

from typing import Any

from yoke_contracts.timestamps import parse_instant, temporal_wire, utc_now

from yoke_core.domain import db_backend
from yoke_core.domain.actors import ActorNotFound


def invite_state(row: dict) -> str:
    if row["consumed_at"] is not None:
        return "consumed"
    if row["revoked_at"] is not None or row["replaced_at"] is not None:
        return "revoked"
    return "expired" if parse_instant(row["expires_at"]) <= utc_now() else "pending"


def public_invites(conn: Any, rows: list[dict]) -> list[dict]:
    """Resolve names once for a collection, retaining the original wire fields."""
    if not rows:
        return []
    ids = sorted(
        {
            row[key]
            for row in rows
            for key in ("actor_id", "invited_by_actor_id")
            if row[key] is not None
        }
    )
    placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"
    names = dict(
        conn.execute(
            f"SELECT id, name FROM actors WHERE id IN ({','.join([placeholder] * len(ids))})",
            tuple(ids),
        ).fetchall()
    )
    result = []
    for row in rows:
        if row["actor_id"] not in names:
            raise ActorNotFound(f"actor id {row['actor_id']} does not exist")
        inviter = names.get(row["invited_by_actor_id"]) or ""
        result.append(
            temporal_wire(
                {
                    "invite_id": row["id"],
                    "ref": f"code-{row['id']}",
                    "kind": "code",
                    "actor_id": row["actor_id"],
                    "name": names[row["actor_id"]] or "",
                    "role": row["role"],
                    "state": invite_state(row),
                    "created_at": row["created_at"],
                    "expires_at": row["expires_at"],
                    "invited_by": inviter,
                    "invited_by_name": inviter.strip() or None,
                }
            )
        )
    return result
