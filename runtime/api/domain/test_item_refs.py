"""Project-qualified SQL references stay current without stored copies."""

import sqlite3

import pytest

from runtime.api.conftest import insert_item
from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain.schema_init_tables import create_core_tables
from yoke_core.domain.item_refs_schema import ensure_item_refs_view


def _assert_refs(conn):
    rows = conn.execute(
        "SELECT i.id, i.project_id, p.slug, p.public_item_prefix, "
        "i.project_sequence, r.item_id, r.project_id, r.public_ref "
        "FROM items i JOIN projects p ON p.id = i.project_id "
        "JOIN item_refs r ON r.item_id = i.id ORDER BY i.id"
    ).fetchall()
    assert len(rows) == conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    for row in rows:
        assert row[0:2] == row[5:7]
        assert row[7] == format_item_ref(row[2], row[3], row[4])


def test_refs_match_python_across_projects_and_prefix_updates(test_db):
    test_db.execute(
        "INSERT INTO projects (id, slug, name, public_item_prefix, created_at, updated_at) "
        "VALUES (77, 'other', 'Other', 'OTH', '2026-10-04', '2026-10-04')"
    )
    for project_id, item_id in [(1, 7800), (77, 7801)]:
        insert_item(test_db, id=item_id, project_id=project_id, project_sequence=158)
    _assert_refs(test_db)
    test_db.execute("UPDATE projects SET public_item_prefix = 'NEW' WHERE id = 77")
    _assert_refs(test_db)
    assert (
        test_db.execute(
            "SELECT public_ref FROM item_refs WHERE item_id = 7801"
        ).fetchone()[0]
        == "NEW-158"
    )


def test_additive_core_schema_creates_missing_view_and_is_idempotent(test_db):
    test_db.execute("DROP VIEW item_refs")
    create_core_tables(test_db)
    create_core_tables(test_db)
    _assert_refs(test_db)
    assert (
        test_db.execute(
            "SELECT is_updatable FROM information_schema.views "
            "WHERE table_name = 'item_refs'"
        ).fetchone()[0]
        == "NO"
    )


def test_sqlite_validation_projection_is_read_only_and_current():
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(
            "CREATE TABLE projects (id INTEGER, public_item_prefix TEXT);"
            "CREATE TABLE items (id INTEGER, project_id INTEGER, project_sequence INTEGER);"
            "INSERT INTO projects VALUES (1, 'ONE'), (2, 'TWO');"
            "INSERT INTO items VALUES (10, 1, 158), (20, 2, 158);"
        )
        ensure_item_refs_view(conn)
        ensure_item_refs_view(conn)
        assert conn.execute("SELECT * FROM item_refs ORDER BY item_id").fetchall() == [
            (10, 1, "ONE-158"),
            (20, 2, "TWO-158"),
        ]
        conn.execute("UPDATE projects SET public_item_prefix = 'NEW' WHERE id = 2")
        assert (
            conn.execute(
                "SELECT public_ref FROM item_refs WHERE item_id = 20"
            ).fetchone()[0]
            == "NEW-158"
        )
        with pytest.raises(sqlite3.OperationalError, match="view"):
            conn.execute("UPDATE item_refs SET public_ref = 'changed'")
    finally:
        conn.close()
