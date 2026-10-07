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
    sequence = 158
    test_db.execute(
        "INSERT INTO projects (id, slug, name, public_item_prefix, created_at) "
        "VALUES (77, 'other', 'Other', 'OTH', '2026-10-04')"
    )
    for project_id, item_id in [(1, 7800), (77, 7801)]:
        insert_item(
            test_db, id=item_id, project_id=project_id, project_sequence=sequence
        )
    _assert_refs(test_db)
    test_db.execute("UPDATE projects SET public_item_prefix = 'NEW' WHERE id = 77")
    _assert_refs(test_db)
    assert (
        test_db.execute(
            "SELECT public_ref FROM item_refs WHERE item_id = 7801"
        ).fetchone()[0]
        == f"NEW-{sequence}"
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


def test_prefix_rekey_preserves_archived_shepherd_evidence_and_links(test_db):
    from yoke_core.domain.project_public_prefix import rekey_shepherd_refs

    stamp = "2026-01-01T00:00:00Z"
    test_db.execute(
        "INSERT INTO shepherd_verdicts "
        "(id, public_ref, archived_item_key, transition, worker, verdict, created_at) VALUES "
        "(1, 'OLD-7', NULL, 'review', 'reviewer', 'GO', %s), "
        "(2, NULL, 'OLD-999', 'review', 'reviewer', 'GO', %s)",
        (stamp, stamp),
    )
    test_db.execute(
        "INSERT INTO caveat_dispositions "
        "(id, public_ref, archived_item_key, transition, caveat_num, "
        "caveat_text, disposition, verdict_id, created_at) VALUES "
        "(1, 'OLD-7', NULL, 'review', 1, 'active', 'RESOLVED', 1, %s), "
        "(2, NULL, 'OLD-999', 'review', 1, 'archived', 'DEFERRED', 2, %s)",
        (stamp, stamp),
    )
    rekey_shepherd_refs(test_db, "OLD", "NEW")
    for table in ("shepherd_verdicts", "caveat_dispositions"):
        assert [
            tuple(row)
            for row in test_db.execute(
                f"SELECT id, public_ref, archived_item_key FROM {table} ORDER BY id"
            )
        ] == [(1, "NEW-7", None), (2, None, "OLD-999")]
    assert [
        tuple(row)
        for row in test_db.execute(
            "SELECT id, verdict_id FROM caveat_dispositions ORDER BY id"
        )
    ] == [(1, 1), (2, 2)]


def test_sqlite_validation_projection_is_read_only_and_current():
    sequence = 158
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(
            "CREATE TABLE projects (id INTEGER, public_item_prefix TEXT);"
            "CREATE TABLE items (id INTEGER, project_id INTEGER, project_sequence INTEGER);"
            "INSERT INTO projects VALUES (1, 'ONE'), (2, 'TWO');"
            f"INSERT INTO items VALUES (10, 1, {sequence}), (20, 2, {sequence});"
        )
        ensure_item_refs_view(conn)
        ensure_item_refs_view(conn)
        assert conn.execute("SELECT * FROM item_refs ORDER BY item_id").fetchall() == [
            (10, 1, f"ONE-{sequence}"),
            (20, 2, f"TWO-{sequence}"),
        ]
        conn.execute("UPDATE projects SET public_item_prefix = 'NEW' WHERE id = 2")
        assert (
            conn.execute(
                "SELECT public_ref FROM item_refs WHERE item_id = 20"
            ).fetchone()[0]
            == f"NEW-{sequence}"
        )
        with pytest.raises(sqlite3.OperationalError, match="view"):
            conn.execute("UPDATE item_refs SET public_ref = 'changed'")
    finally:
        conn.close()
