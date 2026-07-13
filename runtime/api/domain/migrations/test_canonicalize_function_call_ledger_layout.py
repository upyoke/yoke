"""Governed migration tests for the canonical function-call ledger layout."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from runtime.api.domain.migrations import (
    canonicalize_function_call_ledger_layout as migration,
)
from runtime.api.fixtures import pg_testdb
from yoke_core.domain.environment_bootstrap import run_init_chain_at_dsn
from yoke_core.domain.portable_migration import (
    apply_manifest,
    load_packaged_modules,
    parse_manifest_text,
)


ROOT = Path(__file__).resolve().parents[4]
MANIFEST = (
    ROOT / "runtime/api/domain/migrations/"
    "canonicalize_function_call_ledger_layout.migration.json"
)


@pytest.fixture
def reordered_conn() -> Iterator[Any]:
    name = pg_testdb.create_test_database()
    dsn = pg_testdb.dsn_for_test_database(name)
    run_init_chain_at_dsn(dsn, emit=lambda _line: None)
    conn = pg_testdb.connect_test_database(name)
    try:
        conn.execute(f"DROP TABLE {migration.TABLE}")
        conn.execute(
            f"CREATE TABLE {migration.TABLE} ("
            "request_id TEXT PRIMARY KEY, "
            "function_id TEXT NOT NULL, "
            "result TEXT, "
            "created_at TEXT NOT NULL, "
            "actor_id TEXT NOT NULL DEFAULT '', "
            "authorization_scope TEXT NOT NULL DEFAULT '', "
            "payload_checksum TEXT NOT NULL DEFAULT '')"
        )
        conn.execute(
            f"CREATE INDEX idx_{migration.TABLE}_created "
            f"ON {migration.TABLE}(created_at)"
        )
        conn.execute(
            f"INSERT INTO {migration.TABLE} "
            "(request_id, function_id, result, created_at, actor_id, "
            "authorization_scope, payload_checksum) VALUES "
            "('request-1', 'items.get', '{\"ok\":true}', "
            "'2026-07-13T00:00:00Z', 'actor-1', 'project:yoke', 'checksum-1')"
        )
        conn.commit()
        yield conn
    finally:
        conn.close()
        pg_testdb.drop_test_database(name)


def test_apply_converges_column_order_without_changing_content(
    reordered_conn: Any,
) -> None:
    migration.apply(reordered_conn)
    reordered_conn.commit()

    migration.invariants(reordered_conn)
    assert migration.column_order(reordered_conn, migration.TABLE) == (
        migration.EXPECTED_COLUMNS
    )
    assert reordered_conn.execute(
        f"SELECT request_id, function_id, actor_id, authorization_scope, "
        f"payload_checksum, result, created_at FROM {migration.TABLE}"
    ).fetchall() == [
        (
            "request-1",
            "items.get",
            "actor-1",
            "project:yoke",
            "checksum-1",
            '{"ok":true}',
            "2026-07-13T00:00:00Z",
        )
    ]


def test_apply_is_idempotent(reordered_conn: Any) -> None:
    migration.apply(reordered_conn)
    migration.apply(reordered_conn)
    reordered_conn.commit()

    migration.invariants(reordered_conn)


def test_apply_refuses_columns_that_differ_beyond_order(
    reordered_conn: Any,
) -> None:
    reordered_conn.execute(f"ALTER TABLE {migration.TABLE} ADD COLUMN unexpected TEXT")
    assert "unexpected" in migration.column_order(reordered_conn, migration.TABLE)

    with pytest.raises(AssertionError, match="differ beyond order"):
        migration.apply(reordered_conn)
    reordered_conn.rollback()

    assert "unexpected" not in migration.column_order(reordered_conn, migration.TABLE)


def test_public_manifest_loads_exact_module_and_applies(
    reordered_conn: Any,
) -> None:
    manifest = parse_manifest_text(MANIFEST.read_text(encoding="utf-8"))

    assert manifest.module_identifiers == ("canonicalize_function_call_ledger_layout",)
    assert manifest.affected_tables == (migration.TABLE,)
    assert load_packaged_modules(manifest)[0].__name__ == (
        "yoke_core.domain.migrations.canonicalize_function_call_ledger_layout"
    )

    result = apply_manifest(reordered_conn, manifest)

    assert result.modules == ("canonicalize_function_call_ledger_layout",)
    assert result.pre_row_counts == {migration.TABLE: 1}
    assert result.post_row_counts == {migration.TABLE: 1}
    migration.invariants(reordered_conn)
