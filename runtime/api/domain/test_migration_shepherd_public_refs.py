"""Rehearse Shepherd identity conversion against its historical table shape."""

from __future__ import annotations

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain import migrations
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)
from yoke_core.domain.migration_serving_version import NEXT_RELEASE, declared_minimum
from yoke_core.domain.schema_common import _column_exists


@pytest.fixture
def entry():
    record = next(
        e
        for e in ordered_entries(history_dir(migrations))
        if e.name.endswith("_shepherd_public_refs")
    )
    return load_migration_module(record.path, record.name)


@pytest.fixture
def historical_db():
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    conn.execute(
        "CREATE TABLE projects (id INTEGER PRIMARY KEY, public_item_prefix TEXT)"
    )
    conn.execute(
        "CREATE TABLE items (id INTEGER PRIMARY KEY, project_id INTEGER, project_sequence INTEGER)"
    )
    conn.execute(
        "CREATE TABLE shepherd_verdicts (id INTEGER PRIMARY KEY, item TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE caveat_dispositions (id INTEGER PRIMARY KEY, item TEXT NOT NULL, "
        "transition TEXT, attempt INTEGER, caveat_num INTEGER, verdict_id INTEGER "
        "REFERENCES shepherd_verdicts(id), UNIQUE(item, transition, attempt, caveat_num))"
    )
    conn.execute("INSERT INTO projects VALUES (1, 'YOK'), (2, 'APP')")
    conn.execute("INSERT INTO items VALUES (11, 1, 12), (12, 1, 11), (13, 2, 11)")
    for item_id in (11, 12, 13):
        conn.execute(
            "INSERT INTO shepherd_verdicts VALUES (%s, %s)", (item_id, f"YOK-{item_id}")
        )
        conn.execute(
            "INSERT INTO caveat_dispositions VALUES (%s, %s, 'review', 1, 1, %s)",
            (item_id, f"YOK-{item_id}", item_id),
        )
    conn.commit()
    try:
        yield conn
    finally:
        conn.close()
        pg_testdb.drop_test_database(name)


def test_keys_follow_project_sequences_and_preserve_record_links(entry, historical_db):
    conn = historical_db
    entry.apply(conn)
    entry.invariants(conn)
    conn.commit()
    expected = {11: f"YOK-{12}", 12: f"YOK-{11}", 13: f"APP-{11}"}
    assert (
        dict(conn.execute("SELECT id, public_ref FROM shepherd_verdicts").fetchall())
        == expected
    )
    assert (
        dict(conn.execute("SELECT id, public_ref FROM caveat_dispositions").fetchall())
        == expected
    )
    assert all(
        a == b
        for a, b in conn.execute("SELECT id, verdict_id FROM caveat_dispositions")
    )
    assert not _column_exists(conn, "shepherd_verdicts", "item")
    assert not _column_exists(conn, "caveat_dispositions", "item")
    entry.apply(conn)
    entry.invariants(conn)
    assert (
        dict(conn.execute("SELECT id, public_ref FROM shepherd_verdicts").fetchall())
        == expected
    )


def test_orphan_keys_are_archived_without_losing_rows_or_caveat_links(
    entry, historical_db
):
    conn = historical_db
    conn.execute("INSERT INTO shepherd_verdicts VALUES (99, 'orphan')")
    conn.execute(
        "INSERT INTO caveat_dispositions VALUES (99, 'YOK-999', 'review', 1, 1, 99)"
    )
    conn.commit()
    entry.apply(conn)
    entry.invariants(conn)
    conn.commit()
    assert tuple(
        conn.execute(
            "SELECT public_ref, archived_item_key FROM shepherd_verdicts WHERE id = 99"
        ).fetchone()
    ) == (None, "orphan")
    assert tuple(
        conn.execute(
            "SELECT public_ref, archived_item_key, verdict_id FROM caveat_dispositions WHERE id = 99"
        ).fetchone()
    ) == (None, "YOK-999", 99)
    for table in ("shepherd_verdicts", "caveat_dispositions"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 4
    entry.apply(conn)
    entry.invariants(conn)


def test_cutover_declares_serving_floor(entry):
    assert declared_minimum(entry) == NEXT_RELEASE
