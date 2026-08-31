"""Ordered migration coverage for scoping actor-label uniqueness."""

from __future__ import annotations

import psycopg
import pytest

from runtime.api.fixtures import pg_testdb
from yoke_contracts.actor_labels import (
    DISPLAY_LABEL_SURFACE,
    GITHUB_LABEL_SURFACE,
)
from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)
from yoke_core.domain.migration_serving_version import NEXT_RELEASE, declared_minimum
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    RESOLUTION_LABEL_INDEX,
    create_actor_identity_tables,
)


ENTRY_NAME = "0031_actor_display_label_not_a_resolution_key"


def _entry():
    record = next(
        candidate
        for candidate in ordered_entries(history_dir(migration_history_package))
        if candidate.name == ENTRY_NAME
    )
    return load_migration_module(record.path, record.name)


entry = _entry()


def _actor(conn) -> int:
    row = conn.execute(
        "INSERT INTO actors (kind, system_component, created_at) "
        "VALUES ('human', NULL, '2026-01-01T00:00:00Z') RETURNING id"
    ).fetchone()
    return int(row[0])


def _label(conn, actor_id: int, surface: str, label: str) -> None:
    conn.execute(
        "INSERT INTO actor_labels (actor_id, surface, label, created_at) "
        "VALUES (%s, %s, %s, '2026-01-01T00:00:00Z')",
        (actor_id, surface, label),
    )


@pytest.fixture
def pre_entry_db():
    """A universe still carrying the global UNIQUE(surface, label)."""
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    conn.execute(
        """
        CREATE TABLE actors (
            id SERIAL PRIMARY KEY,
            kind TEXT NOT NULL,
            system_component TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE actor_labels (
            id SERIAL PRIMARY KEY,
            actor_id INTEGER NOT NULL REFERENCES actors(id),
            surface TEXT NOT NULL,
            label TEXT NOT NULL,
            created_at TEXT NOT NULL,
            CONSTRAINT actor_labels_surface_label_key UNIQUE (surface, label),
            UNIQUE (actor_id, surface)
        )
        """
    )
    conn.commit()
    try:
        yield conn
    finally:
        conn.close()
        pg_testdb.drop_test_database(name)


def test_entry_requires_the_next_release_serving_floor() -> None:
    assert declared_minimum(entry) == NEXT_RELEASE


def test_two_members_may_share_a_display_name_after_the_entry(pre_entry_db) -> None:
    first = _actor(pre_entry_db)
    second = _actor(pre_entry_db)
    _label(pre_entry_db, first, DISPLAY_LABEL_SURFACE, "Alex Kim")
    pre_entry_db.commit()
    with pytest.raises(psycopg.errors.UniqueViolation):
        _label(pre_entry_db, second, DISPLAY_LABEL_SURFACE, "Alex Kim")
    pre_entry_db.rollback()

    entry.apply(pre_entry_db)
    entry.apply(pre_entry_db)
    entry.invariants(pre_entry_db)
    pre_entry_db.commit()

    _label(pre_entry_db, second, DISPLAY_LABEL_SURFACE, "Alex Kim")
    pre_entry_db.commit()
    holders = pre_entry_db.execute(
        "SELECT COUNT(*) FROM actor_labels WHERE surface = %s AND label = %s",
        (DISPLAY_LABEL_SURFACE, "Alex Kim"),
    ).fetchone()
    assert holders[0] == 2


def test_resolution_surfaces_stay_uniquely_keyed(pre_entry_db) -> None:
    first = _actor(pre_entry_db)
    second = _actor(pre_entry_db)
    entry.apply(pre_entry_db)
    pre_entry_db.commit()

    _label(pre_entry_db, first, GITHUB_LABEL_SURFACE, "shared-handle")
    pre_entry_db.commit()
    with pytest.raises(psycopg.errors.UniqueViolation):
        _label(pre_entry_db, second, GITHUB_LABEL_SURFACE, "shared-handle")
    pre_entry_db.rollback()


def test_entry_is_a_no_op_on_a_universe_born_after_it() -> None:
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    def _indexes() -> set[str]:
        return {
            row[0]
            for row in conn.execute(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'actor_labels'"
            ).fetchall()
        }

    try:
        create_actor_identity_tables(conn)
        born = _indexes()
        assert RESOLUTION_LABEL_INDEX in born
        entry.apply(conn)
        entry.invariants(conn)
        conn.commit()
        # The entry spells its index name out rather than importing the live
        # constant, so applying it to a universe already born with that index
        # must add nothing. A second index here would mean the two spellings
        # have drifted apart.
        assert _indexes() == born

        first = _actor(conn)
        second = _actor(conn)
        _label(conn, first, DISPLAY_LABEL_SURFACE, "Alex Kim")
        _label(conn, second, DISPLAY_LABEL_SURFACE, "Alex Kim")
        conn.commit()
    finally:
        conn.close()
        pg_testdb.drop_test_database(name)


def test_entry_skips_a_database_without_the_table() -> None:
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    try:
        entry.apply(conn)
        entry.invariants(conn)
    finally:
        conn.close()
        pg_testdb.drop_test_database(name)
