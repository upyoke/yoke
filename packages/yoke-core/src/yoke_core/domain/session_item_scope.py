"""The item a session holds, or the one it most recently released.

Ordinary ``--steering`` mail still derives its address from a live claim
first, then the item this session most recently released, so a worker can
report after close-out. A DONE heading names PREFIX-N instead; that named
item is validated against these same claims rather than substituting a
different live hold.

The lookback stays inside the session: a claim this session released is
work this session did, while another session's released claim is not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.work_claim_targets import TARGET_KIND_ITEM, decode_scope


@dataclass(frozen=True)
class SessionItemScope:
    """The item naming a session's work, and the project that holds it."""

    item_id: int
    project_id: int
    live: bool


def _iter_item_scopes(conn: Any, session_id: str) -> list[SessionItemScope]:
    """Live item claims first, then this session's released item claims."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT wc.scope AS scope, wc.released_at AS released_at "
        "FROM work_claims wc "
        f"WHERE wc.session_id = {marker} AND wc.target_kind = {marker} "
        "ORDER BY (wc.released_at IS NULL) DESC, wc.released_at DESC, "
        "wc.claimed_at DESC, wc.id DESC",
        (str(session_id), TARGET_KIND_ITEM),
    ).fetchall()
    scopes: list[SessionItemScope] = []
    seen: set[int] = set()
    for row in rows:
        record = dict(row)
        item_id = int(decode_scope(record["scope"])["item_id"])
        if item_id in seen:
            continue
        item = conn.execute(
            f"SELECT project_id FROM items WHERE id = {marker}",
            (item_id,),
        ).fetchone()
        if item is None:
            continue
        seen.add(item_id)
        scopes.append(
            SessionItemScope(
                item_id=item_id,
                project_id=int(dict(item)["project_id"]),
                live=record["released_at"] is None,
            )
        )
    return scopes


def session_item_scope(conn: Any, session_id: str | None) -> SessionItemScope | None:
    """Return the item this session holds, else the one it last released."""
    if not session_id:
        return None
    scopes = _iter_item_scopes(conn, session_id)
    return scopes[0] if scopes else None


def session_claim_for_item(
    conn: Any, session_id: str | None, item_id: int
) -> SessionItemScope | None:
    """The live or released item claim this session has on *item_id*."""
    if not session_id:
        return None
    wanted = int(item_id)
    for scope in _iter_item_scopes(conn, session_id):
        if scope.item_id == wanted:
            return scope
    return None


__all__ = [
    "SessionItemScope",
    "session_claim_for_item",
    "session_item_scope",
]
