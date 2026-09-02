"""The item a session holds, or the one it most recently released.

A worker addresses the steering seat by the work it is doing, and the
report that matters most -- this item is finished -- is written at the one
moment the worker no longer holds the item: close-out releases the claim
before the report is written. Deriving that address from a LIVE claim
alone refused exactly the send the mandate asked for, so the worker
re-addressed the same report another way and the seat received it twice.
Reading the released claim too lets one report reach the seat once, before
or after close-out.

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


def session_item_scope(
    conn: Any, session_id: str | None
) -> SessionItemScope | None:
    """Return the item this session holds, else the one it last released."""
    if not session_id:
        return None
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT wc.scope AS scope, wc.released_at AS released_at "
        "FROM work_claims wc "
        f"WHERE wc.session_id = {marker} AND wc.target_kind = {marker} "
        "ORDER BY (wc.released_at IS NULL) DESC, wc.released_at DESC, "
        "wc.claimed_at DESC, wc.id DESC",
        (str(session_id), TARGET_KIND_ITEM),
    ).fetchall()
    for row in rows:
        record = dict(row)
        item_id = int(decode_scope(record["scope"])["item_id"])
        item = conn.execute(
            f"SELECT project_id FROM items WHERE id = {marker}",
            (item_id,),
        ).fetchone()
        if item is not None:
            return SessionItemScope(
                item_id=item_id,
                project_id=int(dict(item)["project_id"]),
                live=record["released_at"] is None,
            )
    return None


__all__ = ["SessionItemScope", "session_item_scope"]
