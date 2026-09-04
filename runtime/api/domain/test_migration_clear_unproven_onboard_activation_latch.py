"""The history entry that drops an onboarding latch no complete run backs."""

from __future__ import annotations

import sqlite3

import pytest

from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)


ENTRY_NAME = "0035_clear_unproven_onboard_activation_latch"


def _entry():
    directory = history_dir(migration_history_package)
    record = next(
        entry for entry in ordered_entries(directory) if entry.name == ENTRY_NAME
    )
    return load_migration_module(directory / f"{record.name}.py", record.name)


entry = _entry()


def _universe(*, latched: bool = True) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        f"CREATE TABLE {entry.FACTS_TABLE} ("
        "module_key TEXT PRIMARY KEY, activated_at TEXT NOT NULL)"
    )
    conn.execute(
        f"CREATE TABLE {entry.RUNS_TABLE} ("
        "run_id TEXT PRIMARY KEY, project_id INTEGER, "
        "status TEXT NOT NULL, metadata_json TEXT NOT NULL, "
        "updated_at TEXT NOT NULL)"
    )
    conn.execute(
        f"CREATE TABLE {entry.ROWS_TABLE} ("
        "run_id TEXT NOT NULL, row_id TEXT NOT NULL, status TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE deployment_runs ("
        "id TEXT PRIMARY KEY, project_id INTEGER NOT NULL, status TEXT NOT NULL, "
        "created_at TEXT NOT NULL, completed_at TEXT)"
    )
    conn.execute(
        f"INSERT INTO {entry.FACTS_TABLE} VALUES "
        "('connect_harness', '2026-09-01T00:00:00Z')"
    )
    if latched:
        conn.execute(
            f"INSERT INTO {entry.FACTS_TABLE} VALUES "
            f"('{entry.MODULE_KEY}', '2026-09-02T00:00:00Z')"
        )
    return conn


def _run(conn: sqlite3.Connection, run_id: str, statuses: tuple[str, ...]) -> None:
    conn.execute(
        f"INSERT INTO {entry.RUNS_TABLE} "
        "(run_id, project_id, status, metadata_json, updated_at) VALUES "
        f"('{run_id}', 1, 'open', '{{}}', '2026-08-01T00:00:00Z')"
    )
    for index, status in enumerate(statuses):
        conn.execute(
            f"INSERT INTO {entry.ROWS_TABLE} VALUES "
            f"('{run_id}', 'row-{index}', '{status}')",
        )


def _latched_modules(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            f"SELECT module_key FROM {entry.FACTS_TABLE}"
        ).fetchall()
    }


def test_standing_invariant_does_not_recognize_deployment_supersession() -> None:
    conn = _universe()
    _run(conn, "run-stalled", ("verified", "blocked"))
    conn.execute(
        "INSERT INTO deployment_runs VALUES "
        "('run-20260901-001', 1, 'succeeded', "
        "'2026-09-01T00:00:00Z', '2026-09-01T00:05:00Z')"
    )

    with pytest.raises(AssertionError, match="fully closed checklist"):
        entry.invariants(conn)

    assert _latched_modules(conn) == {"connect_harness", entry.MODULE_KEY}


def test_apply_still_removes_an_unproven_latch() -> None:
    conn = _universe()

    entry.apply(conn)

    assert _latched_modules(conn) == {"connect_harness"}


def test_entry_clears_the_latch_a_blocked_run_once_produced() -> None:
    conn = _universe()
    _run(conn, "run-blocked", ("verified", "blocked", "needed"))

    entry.apply(conn)
    entry.invariants(conn)

    assert _latched_modules(conn) == {"connect_harness"}


def test_entry_keeps_the_latch_a_finished_checklist_earned() -> None:
    conn = _universe()
    _run(conn, "run-done", ("verified", "not-needed", "deferred"))

    entry.apply(conn)
    entry.invariants(conn)

    assert _latched_modules(conn) == {"connect_harness", entry.MODULE_KEY}


def test_entry_reads_a_run_row_with_no_checklist_as_unfinished() -> None:
    conn = _universe()
    _run(conn, "run-empty", ())

    entry.apply(conn)
    entry.invariants(conn)

    assert _latched_modules(conn) == {"connect_harness"}


def test_entry_is_idempotent_and_leaves_an_unlatched_universe_alone() -> None:
    conn = _universe(latched=False)
    _run(conn, "run-open", ("needed",))

    entry.apply(conn)
    entry.apply(conn)
    entry.invariants(conn)

    assert _latched_modules(conn) == {"connect_harness"}


def test_entry_leaves_a_database_without_the_activation_table_alone() -> None:
    conn = sqlite3.connect(":memory:")

    entry.apply(conn)
    entry.invariants(conn)
