"""Visitor links: which anonymous browser visitor ids belong to which actor.

A browser's analytics visitor id is the ``visitor_id`` in its server-signed
attribution cookie, stamped on every page view it sends. Each web sign-in
records the browser's verified visitor id against the signed-in actor here,
so one actor accumulates one link per browser or device it signs in from.

The links follow the identity-stitching model analytics tools use: a visitor
id belongs to at most one actor and is never re-linked, page views are never
rewritten, and a reader ties anonymous page views to their actor at query
time by joining ``events.visitor_id`` to this table. Sign-out clears the
attribution cookie, so the next visitor on a shared browser starts under a
fresh id instead of inheriting the previous person's.

``actors.attribution`` stays the signup snapshot; this table is the durable
list of every browser later linked to the actor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from yoke_core.domain.schema_init_apply import execute_schema_script

VISITOR_LINK_TABLE = "actor_visitor_links"

LINKED = "linked"
ALREADY_LINKED = "already_linked"
#: Named refusal: the visitor id already belongs to a different actor.
LINKED_TO_OTHER_ACTOR = "visitor_linked_to_other_actor"


@dataclass(frozen=True)
class VisitorLinkResult:
    outcome: str
    visitor_id: str
    actor_id: int
    linked_actor_id: int

    @property
    def refused(self) -> bool:
        return self.outcome == LINKED_TO_OTHER_ACTOR


def create_actor_visitor_links_table(conn: Any) -> None:
    """Create the visitor link table, idempotently (boot converge)."""
    execute_schema_script(
        conn,
        """
        CREATE TABLE IF NOT EXISTS actor_visitor_links (
            visitor_id TEXT PRIMARY KEY,
            actor_id INTEGER NOT NULL REFERENCES actors(id),
            linked_at TEXT NOT NULL,
            refused_actor_id INTEGER REFERENCES actors(id),
            refused_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_actor_visitor_links_actor
            ON actor_visitor_links(actor_id);
    """,
    )


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_visitor_link(
    conn: Any, *, visitor_id: str, actor_id: int
) -> VisitorLinkResult:
    """Link ``visitor_id`` to ``actor_id`` unless another actor already holds it.

    A visitor id held by a different actor is never re-linked: the attempt
    is refused as ``visitor_linked_to_other_actor`` and recorded on the
    existing row (``refused_actor_id`` / ``refused_at``). Commits.
    """
    if not visitor_id:
        raise ValueError("visitor_id_required: link only a verified visitor id")
    now = _now()
    inserted = conn.execute(
        "INSERT INTO actor_visitor_links (visitor_id, actor_id, linked_at) "
        "VALUES (%s, %s, %s) ON CONFLICT (visitor_id) DO NOTHING "
        "RETURNING actor_id",
        (visitor_id, actor_id, now),
    ).fetchone()
    if inserted is not None:
        conn.commit()
        return VisitorLinkResult(LINKED, visitor_id, actor_id, actor_id)
    holder = int(
        conn.execute(
            "SELECT actor_id FROM actor_visitor_links WHERE visitor_id = %s",
            (visitor_id,),
        ).fetchone()[0]
    )
    if holder == actor_id:
        return VisitorLinkResult(ALREADY_LINKED, visitor_id, actor_id, holder)
    conn.execute(
        "UPDATE actor_visitor_links SET refused_actor_id = %s, refused_at = %s "
        "WHERE visitor_id = %s",
        (actor_id, now, visitor_id),
    )
    conn.commit()
    return VisitorLinkResult(LINKED_TO_OTHER_ACTOR, visitor_id, actor_id, holder)


__all__ = [
    "ALREADY_LINKED",
    "LINKED",
    "LINKED_TO_OTHER_ACTOR",
    "VISITOR_LINK_TABLE",
    "VisitorLinkResult",
    "create_actor_visitor_links_table",
    "record_visitor_link",
]
