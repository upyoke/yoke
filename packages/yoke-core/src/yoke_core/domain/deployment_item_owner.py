"""Who an item belongs to, when a notice has to reach a person.

``items.owner`` holds a stringified ``actors.id`` on every row the
current write path produced, and a legacy free-text token such as a bare
name on rows untouched since actors were introduced. A notice addressed
to a person needs the former; the latter is not an address, and
resolving it to "whichever agent holds the claim" would tell the wrong
party while looking like it worked. So this answers ``None`` rather than
guessing, and its callers report that.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.actors import is_human_actor


def item_owner_actor(conn: Any, item_id: int) -> Optional[int]:
    """The human member this item belongs to, or ``None``."""
    row = conn.execute(
        "SELECT owner FROM items WHERE id=%s", (int(item_id),)
    ).fetchone()
    if row is None:
        return None
    raw = str(row["owner"] or "").strip()
    if not raw.isdigit():
        return None
    actor_id = int(raw)
    return actor_id if is_human_actor(conn, actor_id) else None


__all__ = ["item_owner_actor"]
