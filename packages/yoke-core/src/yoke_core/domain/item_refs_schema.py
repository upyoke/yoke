"""Read-only, current project-qualified item references."""

from typing import Any

from yoke_core.domain import db_backend

ITEM_REFS_CREATE_SQL = """
CREATE VIEW item_refs (item_id, project_id, public_ref) AS
SELECT i.id, i.project_id,
       p.public_item_prefix || '-' || CAST(i.project_sequence AS TEXT)
FROM items i JOIN projects p ON p.id = i.project_id;
"""


def ensure_item_refs_view(conn: Any) -> None:
    """Converge the projection after its two source tables exist."""
    create = (
        "CREATE OR REPLACE VIEW"
        if db_backend.connection_is_postgres(conn)
        else "CREATE VIEW IF NOT EXISTS"
    )
    conn.execute(ITEM_REFS_CREATE_SQL.replace("CREATE VIEW", create, 1))
