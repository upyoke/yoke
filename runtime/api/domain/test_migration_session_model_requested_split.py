"""The history entry that moves requested-era model echoes out of `model`."""

from __future__ import annotations

import sqlite3

from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _column_exists


ENTRY_NAME = "0030_session_model_requested_split"


def _entry():
    directory = history_dir(migration_history_package)
    record = next(
        entry for entry in ordered_entries(directory) if entry.name == ENTRY_NAME
    )
    return load_migration_module(directory / f"{record.name}.py", record.name)


entry = _entry()


def _pre_cutover_table() -> sqlite3.Connection:
    """A table shaped the way it was before the split: one model column.

    Nullable here because only the Postgres authority ever holds the
    pre-cutover NOT NULL shape — a SQLite surface builds the table from
    the current DDL. The constraint relaxation itself is covered by
    :func:`test_the_relaxation_runs_only_against_the_postgres_authority`.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute(
        f"CREATE TABLE {entry.TABLE} (session_id TEXT PRIMARY KEY, model TEXT)"
    )
    return conn


class _RecordingPostgresConnection:
    """A Postgres-shaped connection that only records what it was asked."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: str, *args):
        self.statements.append(statement)
        return self


def test_the_relaxation_runs_only_against_the_postgres_authority(
    monkeypatch,
) -> None:
    """The served column must become nullable where the constraint lives."""
    conn = _RecordingPostgresConnection()
    monkeypatch.setattr(
        "yoke_core.domain.db_backend.connection_is_postgres", lambda _conn: True
    )

    entry._drop_model_not_null(conn)

    assert conn.statements == [
        f"ALTER TABLE {entry.TABLE} ALTER COLUMN model DROP NOT NULL"
    ]


def test_the_relaxation_is_skipped_where_no_such_constraint_can_exist(
    monkeypatch,
) -> None:
    conn = _RecordingPostgresConnection()
    monkeypatch.setattr(
        "yoke_core.domain.db_backend.connection_is_postgres", lambda _conn: False
    )

    entry._drop_model_not_null(conn)

    assert conn.statements == []


def _row(conn: sqlite3.Connection, session_id: str) -> tuple:
    return conn.execute(
        f"SELECT model, requested_model FROM {entry.TABLE} WHERE session_id = ?",
        (session_id,),
    ).fetchone()


def test_a_requested_era_echo_becomes_the_request_and_leaves_model_unattested():
    conn = _pre_cutover_table()
    conn.execute(
        f"INSERT INTO {entry.TABLE} VALUES ('s1', 'claude-opus-5[1m]')"
    )

    entry.apply(conn)
    entry.invariants(conn)

    assert _row(conn, "s1") == (None, "claude-opus-5[1m]")


def test_every_split_column_exists_after_the_entry_runs() -> None:
    conn = _pre_cutover_table()

    entry.apply(conn)

    for column, _ddl in entry.REQUESTED_COLUMNS + entry.SERVED_COLUMNS:
        assert _column_exists(conn, entry.TABLE, column), column


def test_a_row_that_already_carries_its_output_is_left_alone() -> None:
    """Re-running must not blank a served value written after the move.

    While the entry sits unapplied the running code can already publish a
    genuine attestation beside the request, so a replay that rewrote every
    row would destroy exactly the fact the split exists to record.
    """
    conn = _pre_cutover_table()
    conn.execute(f"INSERT INTO {entry.TABLE} VALUES ('s1', 'claude-opus-5[1m]')")
    entry.apply(conn)
    conn.execute(
        f"UPDATE {entry.TABLE} SET model = 'claude-opus-5' WHERE session_id = 's1'"
    )

    entry.apply(conn)
    entry.invariants(conn)

    assert _row(conn, "s1") == ("claude-opus-5", "claude-opus-5[1m]")


def test_a_blank_model_moves_to_nothing_rather_than_a_blank_request() -> None:
    conn = _pre_cutover_table()
    conn.execute(f"INSERT INTO {entry.TABLE} VALUES ('s1', '')")

    entry.apply(conn)
    entry.invariants(conn)

    assert _row(conn, "s1") == (None, None)


def test_the_entry_declares_the_next_release_as_its_serving_floor() -> None:
    """A build predating the entry reads model as the session's model."""
    assert entry.MINIMUM_SERVING_VERSION == NEXT_RELEASE
