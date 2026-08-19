"""Catalog-visible columns must not issue ALTER TABLE ADD COLUMN."""

from __future__ import annotations

import re

from yoke_core.domain.schema_common import _add_column_if_not_exists


def test_catalog_present_never_calls_execute(monkeypatch) -> None:
    executed: list[str] = []

    class FakeConn:
        def execute(self, sql, *args, **kwargs):  # noqa: ANN001
            executed.append(str(sql))

    monkeypatch.setattr(
        "yoke_core.domain.schema_common._column_exists",
        lambda *_args, **_kwargs: True,
    )
    _add_column_if_not_exists(FakeConn(), "already_there", "seen", "TEXT")
    assert executed == []


def test_existing_column_does_not_emit_add_column(test_db) -> None:
    test_db.execute(
        "CREATE TABLE catalog_present_add (id INTEGER, already TEXT)"
    )
    statements: list[str] = []
    original = test_db.execute

    def spy(sql, *args, **kwargs):  # noqa: ANN001
        statements.append(str(sql))
        return original(sql, *args, **kwargs)

    test_db.execute = spy
    try:
        _add_column_if_not_exists(
            test_db, "catalog_present_add", "already", "TEXT"
        )
    finally:
        test_db.execute = original

    assert not any(re.search(r"ADD\s+COLUMN", sql, re.I) for sql in statements)
