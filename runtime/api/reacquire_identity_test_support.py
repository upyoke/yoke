"""Project identity for the session-reacquire fixture.

The resume notice names the claims it released, so the fixture needs a
project and an items row to render from. Kept beside the fixture rather
than inside it: the schema module is already at its authored ceiling,
and both the notice tests and the reacquire tests read this.
"""

from __future__ import annotations

from yoke_core.domain import db_backend


_CREATE_IDENTITY = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    public_item_prefix TEXT NOT NULL DEFAULT 'YOK'
);
INSERT INTO projects (id, slug, public_item_prefix)
VALUES (1, 'yoke', 'YOK') ON CONFLICT (id) DO NOTHING;
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL DEFAULT 1,
    project_sequence INTEGER
);
"""

def seed_claim_item(conn, item_id: int, project_sequence: int) -> str:
    """Give a claimed item the identity the resume notice names it by.

    The sequence is deliberately not the internal id, so an assertion on
    the rendered reference cannot pass by the two counters coinciding.
    Returns the public ref the notice will carry.
    """
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    conn.execute(
        "INSERT" + " INTO items (id, project_id, project_sequence) "
        f"VALUES ({marker}, 1, {marker}) ON CONFLICT (id) DO NOTHING",
        (int(item_id), int(project_sequence)),
    )
    conn.commit()
    return f"YOK-{project_sequence}"
