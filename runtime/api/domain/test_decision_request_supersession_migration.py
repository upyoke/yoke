"""Existing Postgres universes widen the status CHECK before replacement writes."""

from importlib import import_module

import pytest
from psycopg.errors import CheckViolation, ForeignKeyViolation

from runtime.api.fixtures.pg_testdb import test_database as database


def test_existing_status_constraint_widens_and_replay_preserves_links():
    migration = import_module(
        "yoke_core.domain.migrations.0112_decision_request_supersession"
    )
    with database() as conn:
        # A narrow standalone table reproduces the pre-migration constraint
        # without touching any production-schema fixtures or dependent tables.
        conn.execute("CREATE SCHEMA old_universe")
        conn.execute("SET search_path TO old_universe, public")
        conn.execute(
            "CREATE TABLE decision_requests (id INTEGER PRIMARY KEY, status TEXT NOT NULL CHECK(status IN ('pending', 'resolved', 'withdrawn')), resolution_note TEXT)"
        )
        conn.execute(
            "INSERT INTO decision_requests VALUES (1, 'resolved', 'Keep this answer'), (2, 'pending', NULL)"
        )
        with pytest.raises(CheckViolation, match="check constraint"):
            with conn.transaction():
                conn.execute(
                    "UPDATE decision_requests SET status='superseded' WHERE id=1"
                )
        migration.apply(conn)
        migration.invariants(conn)
        conn.execute(
            "UPDATE decision_requests SET status='superseded', superseded_by_request_id=2 WHERE id=1"
        )
        migration.apply(conn)
        migration.invariants(conn)
        assert tuple(
            conn.execute(
                "SELECT status, superseded_by_request_id, resolution_note FROM decision_requests WHERE id=1"
            ).fetchone()
        ) == ("superseded", 2, "Keep this answer")
        with pytest.raises(ForeignKeyViolation, match="foreign key constraint"):
            with conn.transaction():
                conn.execute(
                    "UPDATE decision_requests SET superseded_by_request_id=999 WHERE id=1"
                )
