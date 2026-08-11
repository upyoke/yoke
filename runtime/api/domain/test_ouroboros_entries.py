"""Tests for the Ouroboros entry writer.

Body content is written through to the durable row without lexical lint
inspection. Provenance is carried by the ``category`` prefix, not by a
separate writer argument.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.ouroboros_entries import (
    cmd_insert_entry,
    list_entry_rows,
)
from runtime.api.fixtures.file_test_db import init_test_db


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def test_cmd_insert_entry_writes_field_note_category(tmp_db: str) -> None:
    with connect(tmp_db) as conn:
        row_id = cmd_insert_entry(
            conn,
            timestamp="2026-05-26T12:00:00Z",
            agent="engineer",
            context=None,
            category="field-note-observation",
            body="bug: stale doc reference",
        )

    assert row_id.isdigit(), f"expected numeric row id, got {row_id!r}"

    with connect(tmp_db) as conn:
        p = _p(conn)
        cursor = conn.execute(
            f"SELECT category, body FROM ouroboros_entries WHERE id = {p}",
            (int(row_id),),
        )
        row = cursor.fetchone()

    assert row is not None
    assert row[0] == "field-note-observation"
    assert row[1] == "bug: stale doc reference"


def test_cmd_insert_entry_accepts_diagnostic_language(
    tmp_db: str,
) -> None:
    with connect(tmp_db) as conn:
        row_id = cmd_insert_entry(
            conn,
            timestamp="2026-05-26T12:01:00Z",
            agent="operator",
            context=None,
            category="observation",
            body="bug: this is broken",
        )

    assert row_id.isdigit()


def test_cmd_insert_entry_duplicate_skip_unchanged(tmp_db: str) -> None:
    kwargs = dict(
        timestamp="2026-05-26T12:02:00Z",
        agent="engineer",
        context=None,
        category="observation",
        body="duplicate body content",
    )

    with connect(tmp_db) as conn:
        first = cmd_insert_entry(conn, **kwargs)
        second = cmd_insert_entry(conn, **kwargs)

    assert first.isdigit()
    assert second == "Duplicate entry skipped"


def test_list_entry_rows_filters_by_category_prefix(tmp_db: str) -> None:
    with connect(tmp_db) as conn:
        cmd_insert_entry(
            conn,
            timestamp="2026-05-26T12:03:00Z",
            agent="engineer",
            context=None,
            category="field-note-failed",
            body="field-note body",
        )
        cmd_insert_entry(
            conn,
            timestamp="2026-05-26T12:04:00Z",
            agent="engineer",
            context=None,
            category="observation",
            body="ordinary body",
        )
        rows = list_entry_rows(conn, category_prefix="field-note-")

    assert [row["category"] for row in rows] == ["field-note-failed"]


def test_list_entry_rows_honors_limit(tmp_db: str) -> None:
    with connect(tmp_db) as conn:
        for index in range(3):
            cmd_insert_entry(
                conn,
                timestamp=f"2026-05-26T12:0{index}:00Z",
                agent="engineer",
                context=None,
                category="field-note-observation",
                body=f"body {index}",
            )
        rows = list_entry_rows(
            conn, category_prefix="field-note-", limit=2,
        )

    assert [row["body"] for row in rows] == ["body 2", "body 1"]


def test_list_entry_rows_defaults_to_newest_bound(tmp_db: str) -> None:
    from yoke_core.domain.ouroboros_entries import DEFAULT_ENTRY_LIST_LIMIT

    with connect(tmp_db) as conn:
        for index in range(DEFAULT_ENTRY_LIST_LIMIT + 3):
            cmd_insert_entry(
                conn,
                timestamp=f"2026-05-26T12:{index:02d}:00Z",
                agent="engineer",
                context=None,
                category="observation",
                body=f"body {index}",
            )
        rows = list_entry_rows(conn)
        page = list_entry_rows(conn, offset=DEFAULT_ENTRY_LIST_LIMIT)

    assert len(rows) == DEFAULT_ENTRY_LIST_LIMIT
    assert rows[0]["body"] == f"body {DEFAULT_ENTRY_LIST_LIMIT + 2}"
    assert [row["body"] for row in page] == [
        "body 2", "body 1", "body 0",
    ]


def test_count_entry_rows_matches_filters(tmp_db: str) -> None:
    from yoke_core.domain.ouroboros_entries import count_entry_rows

    with connect(tmp_db) as conn:
        cmd_insert_entry(
            conn,
            timestamp="2026-05-26T13:00:00Z",
            agent="engineer",
            context=None,
            category="field-note-failed",
            body="fn",
        )
        cmd_insert_entry(
            conn,
            timestamp="2026-05-26T13:01:00Z",
            agent="engineer",
            context=None,
            category="observation",
            body="plain",
        )
        total = count_entry_rows(conn, category_prefix="field-note-")

    assert total == 1
