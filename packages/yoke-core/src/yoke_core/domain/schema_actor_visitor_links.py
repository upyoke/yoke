"""Additive storage for actor browser visitor links."""

from typing import Any

from yoke_core.domain.schema_init_apply import execute_schema_script


def create_actor_visitor_links_table(conn: Any) -> None:
    """Create the visitor link table, idempotently (boot converge)."""
    execute_schema_script(
        conn,
        """
        CREATE TABLE IF NOT EXISTS actor_visitor_links (
            visitor_id TEXT PRIMARY KEY,
            actor_id INTEGER NOT NULL REFERENCES actors(id),
            linked_at TIMESTAMPTZ NOT NULL,
            refused_actor_id INTEGER REFERENCES actors(id),
            refused_at TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS idx_actor_visitor_links_actor
            ON actor_visitor_links(actor_id);
    """,
    )
