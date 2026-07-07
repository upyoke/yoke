"""Tests for :mod:`yoke_core.domain.schema_readiness`."""

from __future__ import annotations

from pathlib import Path

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain import db_backend
from yoke_core.domain.schema_readiness import (
    READINESS_TABLES,
    missing_readiness_tables,
)


def _apply_tables(names: tuple[str, ...]) -> None:
    conn = db_backend.connect()
    try:
        for name in names:
            conn.execute(f"CREATE TABLE {name} (id INTEGER)")
        conn.commit()
    finally:
        conn.close()


def _missing_on_test_db(db_path: str) -> list[str]:
    conn = connect_test_db(db_path)
    try:
        return missing_readiness_tables(conn)
    finally:
        conn.close()


def test_full_production_schema_reports_ready(tmp_path: Path) -> None:
    """Every readiness table is created by production schema init —
    the canonical set never drifts ahead of what ``cmd_init`` provides."""
    with init_test_db(tmp_path) as db_path:
        assert _missing_on_test_db(db_path) == []


def test_missing_table_is_reported(tmp_path: Path) -> None:
    without_strategy_docs = tuple(
        t for t in READINESS_TABLES if t != "strategy_docs"
    )
    with init_test_db(
        tmp_path, apply_schema=lambda: _apply_tables(without_strategy_docs)
    ) as db_path:
        assert _missing_on_test_db(db_path) == ["strategy_docs"]


def test_empty_db_reports_all_tables_missing(tmp_path: Path) -> None:
    with init_test_db(tmp_path, apply_schema=lambda: None) as db_path:
        assert _missing_on_test_db(db_path) == list(READINESS_TABLES)


def test_explicit_table_subset_overrides_canonical_set(tmp_path: Path) -> None:
    with init_test_db(
        tmp_path, apply_schema=lambda: _apply_tables(("items",))
    ) as db_path:
        conn = connect_test_db(db_path)
        try:
            assert missing_readiness_tables(conn, ("items",)) == []
            assert missing_readiness_tables(conn, ("items", "projects")) == [
                "projects"
            ]
        finally:
            conn.close()
