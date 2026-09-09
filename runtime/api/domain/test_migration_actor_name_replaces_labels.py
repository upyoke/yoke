"""Ordered migration coverage for folding actor labels into actors.name.

The entry runs against real historical shapes, so the fixture builds the
pre-entry schema by hand rather than importing a live module: the table
it converts no longer exists in any current schema module, and a test
that read today's DDL would prove nothing about the databases that
actually need converting.
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)
from yoke_core.domain.migration_serving_version import NEXT_RELEASE, declared_minimum
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_identity_tables,
)


ENTRY_NAME = "0041_actor_name_replaces_actor_labels"

DISPLAY_SURFACE = "display"
GITHUB_SURFACE = "github_label"


def _entry():
    record = next(
        candidate
        for candidate in ordered_entries(history_dir(migration_history_package))
        if candidate.name == ENTRY_NAME
    )
    return load_migration_module(record.path, record.name)


entry = _entry()


def _human(conn, *, name: str | None = None) -> int:
    row = conn.execute(
        "INSERT INTO actors (kind, system_component, created_at) "
        "VALUES ('human', NULL, '2026-01-01T00:00:00Z') RETURNING id"
    ).fetchone()
    actor_id = int(row[0])
    if name is not None:
        conn.execute(
            "UPDATE actors SET name = %s WHERE id = %s", (name, actor_id)
        )
    return actor_id


def _system(conn, component: str) -> int:
    row = conn.execute(
        "INSERT INTO actors (kind, system_component, created_at) "
        "VALUES ('system', %s, '2026-01-01T00:00:00Z') RETURNING id",
        (component,),
    ).fetchone()
    return int(row[0])


def _label(conn, actor_id: int, surface: str, label: str) -> None:
    conn.execute(
        "INSERT INTO actor_labels (actor_id, surface, label, created_at) "
        "VALUES (%s, %s, %s, '2026-01-01T00:00:00Z')",
        (actor_id, surface, label),
    )


def _name(conn, actor_id: int) -> str:
    return str(
        conn.execute(
            "SELECT name FROM actors WHERE id = %s", (actor_id,)
        ).fetchone()[0]
    )


@pytest.fixture
def pre_entry_db():
    """A universe still carrying the per-surface label projection."""
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
            UNIQUE(actor_id, surface)
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX uq_actor_labels_resolution_surface_label "
        "ON actor_labels(surface, label) WHERE surface <> 'display'"
    )
    conn.execute("CREATE INDEX idx_actor_labels_actor ON actor_labels(actor_id)")
    conn.commit()
    try:
        yield conn
    finally:
        conn.close()
        pg_testdb.drop_test_database(name)


def test_entry_declares_the_next_release_serving_floor() -> None:
    """It removes a table every older build reads, so it must declare one."""
    assert declared_minimum(entry) == NEXT_RELEASE


def test_display_name_wins_over_the_github_label(pre_entry_db) -> None:
    actor_id = _human(pre_entry_db)
    _label(pre_entry_db, actor_id, GITHUB_SURFACE, "ada-l")
    _label(pre_entry_db, actor_id, DISPLAY_SURFACE, "Ada Lovelace")
    pre_entry_db.commit()

    entry.apply(pre_entry_db)
    entry.invariants(pre_entry_db)
    pre_entry_db.commit()

    assert _name(pre_entry_db, actor_id) == "Ada Lovelace"


def test_a_github_only_actor_keeps_that_name(pre_entry_db) -> None:
    actor_id = _human(pre_entry_db)
    _label(pre_entry_db, actor_id, GITHUB_SURFACE, "ada-l")
    pre_entry_db.commit()

    entry.apply(pre_entry_db)
    pre_entry_db.commit()

    assert _name(pre_entry_db, actor_id) == "ada-l"


def test_a_system_actor_falls_back_to_its_component(pre_entry_db) -> None:
    actor_id = _system(pre_entry_db, "yoke-core")
    pre_entry_db.commit()

    entry.apply(pre_entry_db)
    pre_entry_db.commit()

    assert _name(pre_entry_db, actor_id) == "yoke-core"


def test_an_actor_with_nothing_to_carry_gets_an_empty_name(pre_entry_db) -> None:
    """Not a guess and not an id — the column is NOT NULL, so it is empty."""
    actor_id = _human(pre_entry_db)
    pre_entry_db.commit()

    entry.apply(pre_entry_db)
    pre_entry_db.commit()

    assert _name(pre_entry_db, actor_id) == ""


def test_two_actors_sharing_a_display_name_both_keep_it(pre_entry_db) -> None:
    """The uniqueness that made this impossible is gone with the table."""
    first = _human(pre_entry_db)
    second = _human(pre_entry_db)
    _label(pre_entry_db, first, DISPLAY_SURFACE, "Alex Kim")
    _label(pre_entry_db, second, DISPLAY_SURFACE, "Alex Kim")
    pre_entry_db.commit()

    entry.apply(pre_entry_db)
    pre_entry_db.commit()

    assert _name(pre_entry_db, first) == "Alex Kim"
    assert _name(pre_entry_db, second) == "Alex Kim"


def test_actor_ids_survive_the_conversion(pre_entry_db) -> None:
    """The identity is the id, so the conversion must not renumber one."""
    first = _human(pre_entry_db)
    second = _human(pre_entry_db)
    system = _system(pre_entry_db, "yoke-core")
    _label(pre_entry_db, first, DISPLAY_SURFACE, "Ada Lovelace")
    pre_entry_db.commit()

    entry.apply(pre_entry_db)
    pre_entry_db.commit()

    ids = [
        int(row[0])
        for row in pre_entry_db.execute(
            "SELECT id FROM actors ORDER BY id"
        ).fetchall()
    ]
    assert ids == sorted([first, second, system])


def test_the_projection_and_its_indexes_are_gone(pre_entry_db) -> None:
    actor_id = _human(pre_entry_db)
    _label(pre_entry_db, actor_id, DISPLAY_SURFACE, "Ada Lovelace")
    pre_entry_db.commit()

    entry.apply(pre_entry_db)
    entry.invariants(pre_entry_db)
    pre_entry_db.commit()

    assert not _table_exists(pre_entry_db, "actor_labels")
    assert _column_exists(pre_entry_db, "actors", "name")
    remaining = {
        row[0]
        for row in pre_entry_db.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'actor_labels'"
        ).fetchall()
    }
    assert remaining == set()


def test_a_name_the_running_code_already_wrote_is_not_overwritten(
    pre_entry_db,
) -> None:
    """Idempotent against its own output, not merely against having run.

    While the entry sits unapplied, the build that ships it can already be
    naming actors through ``actors.name``. Copying a stale label back over
    such a name would undo a rename the account system already made.
    """
    pre_entry_db.execute(
        "ALTER TABLE actors ADD COLUMN name TEXT NOT NULL DEFAULT ''"
    )
    actor_id = _human(pre_entry_db, name="Ada King")
    _label(pre_entry_db, actor_id, DISPLAY_SURFACE, "Ada Lovelace")
    pre_entry_db.commit()

    entry.apply(pre_entry_db)
    pre_entry_db.commit()

    assert _name(pre_entry_db, actor_id) == "Ada King"


def test_reapplying_the_entry_is_a_no_op(pre_entry_db) -> None:
    actor_id = _human(pre_entry_db)
    _label(pre_entry_db, actor_id, DISPLAY_SURFACE, "Ada Lovelace")
    pre_entry_db.commit()

    entry.apply(pre_entry_db)
    pre_entry_db.commit()
    entry.apply(pre_entry_db)
    entry.invariants(pre_entry_db)
    pre_entry_db.commit()

    assert _name(pre_entry_db, actor_id) == "Ada Lovelace"


def test_entry_is_a_no_op_on_a_universe_born_after_it() -> None:
    """A born universe already has the column and never had the table."""
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    try:
        create_actor_identity_tables(conn)
        conn.commit()

        entry.apply(conn)
        entry.invariants(conn)
        conn.commit()

        assert _column_exists(conn, "actors", "name")
        assert not _table_exists(conn, "actor_labels")
    finally:
        conn.close()
        pg_testdb.drop_test_database(name)


def test_entry_skips_a_database_without_an_actors_table() -> None:
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    try:
        entry.apply(conn)
        entry.invariants(conn)
    finally:
        conn.close()
        pg_testdb.drop_test_database(name)
