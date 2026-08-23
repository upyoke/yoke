"""Ordered migration coverage for persisted selected launch surfaces."""

from __future__ import annotations

import sqlite3

import pytest

from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)
from yoke_core.domain.migration_serving_version import NEXT_RELEASE, declared_minimum


ENTRY_NAME = "0018_session_launch_selected_surface"


def _entry():
    record = next(
        candidate
        for candidate in ordered_entries(history_dir(migration_history_package))
        if candidate.name == ENTRY_NAME
    )
    return load_migration_module(record.path, record.name)


entry = _entry()


def _old_connection(surface: str = "codex-vscode") -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE session_launches ("
        "launch_id TEXT PRIMARY KEY,requested_surface TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO session_launches VALUES ('launch-1',?)", (surface,))
    return conn


def test_apply_backfills_old_rows_and_is_idempotent() -> None:
    conn = _old_connection()

    entry.apply(conn)
    entry.apply(conn)
    entry.invariants(conn)

    assert conn.execute(
        "SELECT requested_surface,selected_surface FROM session_launches"
    ).fetchone() == ("codex-vscode", "codex-vscode")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE session_launches SET selected_surface='invented-surface'")


def test_reapply_preserves_a_different_selected_surface() -> None:
    conn = _old_connection()
    entry.apply(conn)
    conn.execute("UPDATE session_launches SET selected_surface='codex-cli'")

    entry.apply(conn)

    assert conn.execute(
        "SELECT requested_surface,selected_surface FROM session_launches"
    ).fetchone() == ("codex-vscode", "codex-cli")


def test_apply_refuses_unknown_historical_requests() -> None:
    conn = _old_connection("invented-surface")

    with pytest.raises(AssertionError, match="unsupported values"):
        entry.apply(conn)

    columns = [row[1] for row in conn.execute("PRAGMA table_info(session_launches)")]
    assert "selected_surface" not in columns


def test_entry_requires_the_next_release_serving_floor() -> None:
    assert declared_minimum(entry) == NEXT_RELEASE
