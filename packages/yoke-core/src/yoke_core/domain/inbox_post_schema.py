"""Durable Inbox posts have one shared completion record."""

from typing import Any

from yoke_core.domain.schema_init_apply import execute_schema_script


def create_inbox_post_table(conn: Any, *, commit: bool = True) -> None:
    execute_schema_script(
        conn,
        """
        CREATE TABLE IF NOT EXISTS inbox_posts (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            audience_id INTEGER NOT NULL REFERENCES audiences(id),
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            fields TEXT NOT NULL DEFAULT '{}',
            source TEXT NOT NULL,
            created_by_actor_id INTEGER NOT NULL REFERENCES actors(id),
            created_at TIMESTAMPTZ NOT NULL,
            done_actor_id INTEGER REFERENCES actors(id),
            done_at TIMESTAMPTZ,
            CHECK ((done_actor_id IS NULL) = (done_at IS NULL))
        );
        CREATE INDEX IF NOT EXISTS idx_inbox_posts_open_audience
            ON inbox_posts(audience_id, project_id, created_at) WHERE done_at IS NULL;
    """,
    )
    if commit:
        conn.commit()
