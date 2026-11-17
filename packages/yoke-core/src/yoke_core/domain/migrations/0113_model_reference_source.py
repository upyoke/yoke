"""Record whose catalog each model catalog revision is: shipped or operator.

A revision an actor published is an operator override; one written without an
actor is the catalog a Yoke build shipped. Boot keeps a universe on shipped
defaults only while its latest revision is shipped-sourced. Replay is a no-op.
"""

from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.schema_common import _column_exists

_TABLE = "model_reference_revisions"


def apply(conn):
    if not _column_exists(conn, _TABLE, "source"):
        conn.execute(f"ALTER TABLE {_TABLE} ADD COLUMN source TEXT")
    conn.execute(
        f"UPDATE {_TABLE} SET source = CASE WHEN published_by_actor_id IS NULL "
        "THEN 'shipped' ELSE 'operator' END WHERE source IS NULL"
    )
    if connection_is_postgres(conn):
        conn.execute(f"ALTER TABLE {_TABLE} ALTER COLUMN source SET NOT NULL")


def invariants(conn):
    assert _column_exists(conn, _TABLE, "source"), f"{_TABLE}.source missing"
    missing = conn.execute(
        f"SELECT COUNT(*) FROM {_TABLE} WHERE source IS NULL "
        "OR source NOT IN ('shipped','operator')"
    ).fetchone()[0]
    assert missing == 0, f"{missing} {_TABLE} rows lack a shipped|operator source"
