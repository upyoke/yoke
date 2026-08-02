"""Validation tests for the governed session-report storage drop."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path
from types import ModuleType

import pytest

from yoke_core.domain.schema_common import _table_exists


def _migration_module() -> ModuleType:
    module_path = Path(__file__).with_name("drop_wrapup_reports.py")
    spec = importlib.util.spec_from_file_location("drop_wrapup_reports", module_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load migration module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MIGRATION = _migration_module()


def _seed_table(conn: sqlite3.Connection, row_count: int) -> None:
    conn.execute(
        f"""
        CREATE TABLE "{MIGRATION.TABLE_NAME}" (
            id INTEGER PRIMARY KEY,
            session_timestamp TEXT NOT NULL UNIQUE,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.executemany(
        f'INSERT INTO "{MIGRATION.TABLE_NAME}" '
        "(session_timestamp, body, created_at) VALUES (?, ?, ?)",
        (
            (f"session-{index}", "body", "2026-08-02T00:00:00Z")
            for index in range(row_count)
        ),
    )


def test_apply_drops_only_the_retired_table() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        _seed_table(conn, MIGRATION.EXPECTED_ROW_COUNT)
        conn.execute("CREATE TABLE ouroboros_entries (id INTEGER PRIMARY KEY)")

        MIGRATION.apply(conn)
        MIGRATION.invariants(conn)

        assert not _table_exists(conn, MIGRATION.TABLE_NAME)
        assert _table_exists(conn, "ouroboros_entries")
    finally:
        conn.close()


def test_apply_rejects_an_unexpected_row_count() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        _seed_table(conn, MIGRATION.EXPECTED_ROW_COUNT - 1)

        with pytest.raises(
            AssertionError,
            match=f"expected {MIGRATION.EXPECTED_ROW_COUNT} rows",
        ):
            MIGRATION.apply(conn)

        assert _table_exists(conn, MIGRATION.TABLE_NAME)
    finally:
        conn.close()


def test_apply_rejects_a_missing_table() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        with pytest.raises(AssertionError, match="table is missing"):
            MIGRATION.apply(conn)
    finally:
        conn.close()


def test_invariants_reject_an_existing_table() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        _seed_table(conn, MIGRATION.EXPECTED_ROW_COUNT)

        with pytest.raises(AssertionError, match="table still exists"):
            MIGRATION.invariants(conn)
    finally:
        conn.close()
