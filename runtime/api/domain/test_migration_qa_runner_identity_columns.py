"""The entry that gives the QA catalog its own word for what runs a case.

Renaming a live column is destructive, so the entry carries a serving floor.
It also has to survive the one ordering the boot converge actually produces:
additive columns are created before the ordered history runs, so a database
can arrive at this entry having already grown the current column as an empty
one. That is the production path, and a plain rename would collide with it.
"""

from __future__ import annotations

import sqlite3

import pytest

from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)
from yoke_core.domain.migration_serving_version import (
    declared_minimum,
    removes_a_surface,
)
from yoke_core.domain.schema_common import _column_exists

ENTRY_NAME = "0008_qa_runner_identity_columns"


def _entry():
    """Load the entry the way the applier does: by path, not by import name."""
    directory = history_dir(migration_history_package)
    match = next(
        record for record in ordered_entries(directory)
        if record.name == ENTRY_NAME
    )
    return load_migration_module(directory / f"{match.name}.py", match.name)


entry = _entry()


def _retired_shape() -> sqlite3.Connection:
    """A database still carrying the retired QA vocabulary."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE qa_methods (
            id TEXT PRIMARY KEY,
            executor_id TEXT NOT NULL,
            executor_gloss TEXT NOT NULL DEFAULT 'registered executor'
        );
        CREATE TABLE qa_requirements (
            id INTEGER PRIMARY KEY,
            executor_id TEXT
        );
        CREATE TABLE qa_runs (
            id INTEGER PRIMARY KEY,
            executor_type TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO qa_methods (id, executor_id, executor_gloss) "
        "VALUES ('command', 'worktree_run', 'runs the command in the worktree')"
    )
    conn.execute(
        "INSERT INTO qa_methods (id, executor_id, executor_gloss) "
        "VALUES ('house-style', 'browser_substrate', 'registered executor')"
    )
    conn.execute(
        "INSERT INTO qa_requirements (id, executor_id) VALUES (1, 'ci_run')"
    )
    conn.execute("INSERT INTO qa_runs (id, executor_type) VALUES (1, 'agent')")
    conn.commit()
    return conn


def _converged_shape() -> sqlite3.Connection:
    """The shape the boot converge leaves behind on the way to this entry.

    ``qa_requirements.runner_id`` and ``qa_methods.runner_gloss`` are declared
    additive columns, so the converge creates them — empty — before the ordered
    history runs.
    """
    conn = _retired_shape()
    conn.execute("ALTER TABLE qa_requirements ADD COLUMN runner_id TEXT")
    conn.execute(
        "ALTER TABLE qa_methods ADD COLUMN runner_gloss TEXT NOT NULL "
        "DEFAULT 'registered runner'"
    )
    conn.commit()
    return conn


def test_each_retired_column_becomes_its_current_name():
    conn = _retired_shape()

    entry.apply(conn)

    for table, retired, current in entry.RENAMED_COLUMNS:
        assert not _column_exists(conn, table, retired)
        assert _column_exists(conn, table, current)


def test_every_value_survives_the_rename():
    """The rename is the whole change; no row's meaning may move with it."""
    conn = _retired_shape()

    entry.apply(conn)

    assert conn.execute(
        "SELECT runner_id FROM qa_methods WHERE id = 'command'"
    ).fetchone()[0] == "worktree_run"
    assert conn.execute(
        "SELECT runner_id FROM qa_requirements WHERE id = 1"
    ).fetchone()[0] == "ci_run"
    assert conn.execute(
        "SELECT performed_by FROM qa_runs WHERE id = 1"
    ).fetchone()[0] == "agent"


def test_the_retired_default_gloss_moves_to_the_current_vocabulary():
    """A row still carrying the old fallback would describe a concept the
    schema no longer has."""
    conn = _retired_shape()

    entry.apply(conn)

    assert conn.execute(
        "SELECT runner_gloss FROM qa_methods WHERE id = 'house-style'"
    ).fetchone()[0] == entry.GLOSS_DEFAULT
    assert conn.execute(
        "SELECT runner_gloss FROM qa_methods WHERE id = 'command'"
    ).fetchone()[0] == "runs the command in the worktree"


def test_an_already_converged_database_folds_instead_of_colliding():
    """The production path: the converge added the current column empty, so a
    plain rename would fail on a name that already exists."""
    conn = _converged_shape()

    entry.apply(conn)

    entry.invariants(conn)
    assert conn.execute(
        "SELECT runner_id FROM qa_requirements WHERE id = 1"
    ).fetchone()[0] == "ci_run"
    assert conn.execute(
        "SELECT runner_gloss FROM qa_methods WHERE id = 'command'"
    ).fetchone()[0] == "runs the command in the worktree"


def test_folding_preserves_the_row_count():
    conn = _converged_shape()
    before = conn.execute("SELECT count(*) FROM qa_requirements").fetchone()[0]

    entry.apply(conn)

    assert conn.execute(
        "SELECT count(*) FROM qa_requirements"
    ).fetchone()[0] == before


def test_applying_twice_is_the_same_as_applying_once():
    """Idempotent against its own output already existing, not merely against
    having run: a database already carrying the current names is finished."""
    conn = _retired_shape()

    entry.apply(conn)
    entry.apply(conn)

    entry.invariants(conn)


def test_invariants_refuse_a_table_that_kept_a_retired_column():
    conn = _retired_shape()

    with pytest.raises(AssertionError, match="retired but still present"):
        entry.invariants(conn)


def test_invariants_refuse_a_table_that_lost_the_current_column():
    """On qa_runs that would be every verdict the universe has recorded."""
    conn = _retired_shape()
    entry.apply(conn)
    conn.execute('ALTER TABLE qa_runs DROP COLUMN "performed_by"')

    with pytest.raises(AssertionError, match="required but absent"):
        entry.invariants(conn)


def test_a_database_without_the_qa_tables_is_left_alone():
    """A universe that never ran QA has nothing to rename."""
    conn = sqlite3.connect(":memory:")

    entry.apply(conn)
    entry.invariants(conn)


def test_the_entry_declares_a_serving_floor_because_it_removes_a_surface():
    """A rolled-back container reports itself current while reading columns
    that no longer answer to those names, so the floor is what refuses it."""
    source = (
        history_dir(migration_history_package) / f"{ENTRY_NAME}.py"
    ).read_text(encoding="utf-8")
    assert removes_a_surface(source)
    assert declared_minimum(entry) == entry.MINIMUM_SERVING_VERSION
