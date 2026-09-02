"""Backlog-related test fixtures: schema DDL, test_db, and insert helpers.

Provides a disposable Postgres database with the full production schema and
convenience insert helpers for common tables. All Yoke API test modules
should use the ``test_db`` fixture rather than creating their own schema setup.

The schema DDL here matches ``runtime/api/domain/schema.py`` exactly
for every column, CHECK constraint, and index — tests need to see the
same shape production emits. No implicit timestamp-default clauses:
insert helpers
below thread :func:`yoke_core.domain.db_helpers.iso8601_now` through
every ``created_at`` / ``updated_at`` column at insert time.  Raw
INSERTs in tests that target the ``test_db`` fixture must supply
``created_at`` themselves; tests that maintain their own in-memory
schema DDL are outside the fixture's contract.

The ``SCHEMA_DDL`` constant is composed by the assembler at
``runtime/api/fixtures/schema_ddl.py`` from three table-family siblings;
the insert helpers live in ``runtime/api/fixtures/backlog_inserts.py``.
This module keeps the pytest fixture (path-based plugin discovery
via ``pytest_plugins`` requires the fixture to live here) and
re-exports the public surface.
"""

from __future__ import annotations

from typing import Any

import pytest

from yoke_core.domain.actors import seed_canonical_actors
from yoke_core.domain.gate_satisfaction_schema import (
    create_gate_satisfaction_tables,
)
from yoke_core.domain.sql_json import JSONB_COLUMNS  # noqa: F401 — imported for cross-reference
from runtime.api.fixtures.backlog_inserts import (
    insert_deployment_run,
    insert_epic_task,
    insert_event,
    insert_item,
    insert_item_worktree,
    insert_qa_requirement,
    insert_qa_run,
)
from runtime.api.fixtures.schema_ddl import SCHEMA_DDL


def seed_test_canonical_actors(conn: Any) -> tuple[int, int]:
    """Seed the canonical yoke-core + local human actors on a fixture DB.

    Mirrors the post-init shape that production
    ``schema_init.cmd_init`` produces, so writer tests that depend on
    actor resolution have the default human actor available without
    every caller re-seeding by hand. Returns
    ``(yoke_core_id, local_human_id)`` exactly like the production
    helper.
    """
    return seed_canonical_actors(conn)


def seed_fixture_operating_actor(conn: Any) -> int:
    """Seed the operating actor session registration binds, when absent.

    Every born universe carries one — ``schema_init.cmd_init`` seeds it —
    and registration refuses rather than storing a NULL actor, so a
    fixture without one models an install that cannot exist. A fixture
    whose schema also carries the org/role tables gets the admin grant a
    real universe gives its operator, because the dispatcher enforces
    permissions as soon as a session names an actor. Idempotent, and a
    minimal ``actors``-only schema still works.
    """
    from yoke_core.domain.actors import seed_human_actor
    from yoke_core.domain.schema_common import _table_exists

    if all(
        _table_exists(conn, table)
        for table in ("actors", "actor_org_roles", "organizations", "roles")
    ):
        from yoke_core.domain.local_operating_actor import (
            ensure_local_operating_actor,
        )

        actor_id, _seeded = ensure_local_operating_actor(conn)
        return actor_id
    row = conn.execute(
        "SELECT id FROM actors WHERE kind = 'human' ORDER BY id LIMIT 1"
    ).fetchone()
    if row is not None:
        return int(row[0])
    return seed_human_actor(conn)


@pytest.fixture
def test_db():
    """Connection with the full Yoke schema on a disposable Postgres DB.

    Seeds the canonical yoke-core + local human actors so writer tests
    resolving the default actor see the same post-init shape production ships.
    """
    from runtime.api.fixtures.pg_testdb import test_database

    with test_database() as conn:
        create_gate_satisfaction_tables(conn)
        seed_test_canonical_actors(conn)
        conn.commit()
        yield conn


__all__ = (
    "JSONB_COLUMNS",
    "SCHEMA_DDL",
    "insert_deployment_run",
    "insert_epic_task",
    "insert_event",
    "insert_item",
    "insert_item_worktree",
    "insert_qa_requirement",
    "insert_qa_run",
    "seed_test_canonical_actors",
    "test_db",
)
