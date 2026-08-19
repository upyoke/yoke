"""An existing lease table must gain owner columns without aborting boot."""

from __future__ import annotations

from importlib import import_module

from yoke_core.domain.schema_common import _column_exists, _get_indexes
from yoke_core.domain.schema_coordination_lease_columns import (
    apply_coordination_lease_columns,
)
from yoke_core.domain.schema_init_tables import create_governed_tables

_mod = import_module(
    "yoke_core.domain.migrations.0011_coordination_lease_typed_ownership"
)

_OLD_LEASE_TABLE = """
CREATE TABLE coordination_leases (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    lease_key TEXT NOT NULL,
    session_id TEXT NOT NULL,
    actor_id TEXT,
    acquired_at TEXT NOT NULL,
    heartbeat_at TEXT,
    released_at TEXT,
    release_reason TEXT
)
"""


def test_behind_lease_table_converges_owner_columns(test_db) -> None:
    test_db.execute("DROP TABLE IF EXISTS coordination_leases CASCADE")
    test_db.execute(_OLD_LEASE_TABLE)
    test_db.execute(
        "INSERT INTO coordination_leases "
        "(id, project_id, lease_key, session_id, acquired_at) "
        "VALUES (1, 1, 'LIVE_DB_MIGRATION:primary', 'sess-1', 'now')"
    )
    test_db.commit()

    create_governed_tables(test_db)
    apply_coordination_lease_columns(test_db)
    assert _column_exists(test_db, "coordination_leases", "owner_item_id")
    assert "idx_coordination_leases_owner_item" in _get_indexes(
        test_db, "coordination_leases"
    )

    _mod.apply(test_db)
    row = test_db.execute(
        "SELECT owner_kind, owner_session_id, owner_item_id "
        "FROM coordination_leases WHERE id = 1"
    ).fetchone()
    assert row["owner_kind"] == "session"
    assert row["owner_session_id"] == "sess-1"
    assert row["owner_item_id"] is None
