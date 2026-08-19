"""Named catalog lookups follow search_path, not only current_schema()."""

from __future__ import annotations

from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _column_exists,
    _table_exists,
)


def test_named_lookup_finds_table_on_search_path(test_db) -> None:
    test_db.execute(
        "CREATE TABLE lease_regclass_probe (id INTEGER, owner_item_id INTEGER)"
    )
    test_db.execute("CREATE SCHEMA extra_search")
    test_db.execute("SET search_path TO extra_search, public")

    assert _table_exists(test_db, "lease_regclass_probe")
    assert _column_exists(test_db, "lease_regclass_probe", "owner_item_id")


def test_add_column_targets_search_path_relation(test_db) -> None:
    test_db.execute("CREATE TABLE lease_regclass_add (id INTEGER)")
    test_db.execute("CREATE SCHEMA extra_search")
    test_db.execute("SET search_path TO extra_search, public")

    _add_column_if_not_exists(
        test_db, "lease_regclass_add", "owner_item_id", "INTEGER DEFAULT NULL"
    )
    _add_column_if_not_exists(
        test_db, "lease_regclass_add", "owner_item_id", "INTEGER DEFAULT NULL"
    )
    assert _column_exists(test_db, "lease_regclass_add", "owner_item_id")
