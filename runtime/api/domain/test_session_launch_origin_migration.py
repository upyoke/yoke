"""Ordered migration coverage for widening session_launches.origin CHECK."""

from __future__ import annotations

import sqlite3

import psycopg
import pytest

from runtime.api.fixtures import pg_testdb
from yoke_contracts.session_control.launch_origin import (
    LAUNCH_ORIGIN_OPERATOR,
    LAUNCH_ORIGIN_STEERING,
)
from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)
from yoke_core.domain.migration_serving_version import NEXT_RELEASE, declared_minimum


ENTRY_NAME = "0029_session_launch_origin_steering"


def _entry():
    record = next(
        candidate
        for candidate in ordered_entries(history_dir(migration_history_package))
        if candidate.name == ENTRY_NAME
    )
    return load_migration_module(record.path, record.name)


entry = _entry()


def test_entry_requires_the_next_release_serving_floor() -> None:
    assert declared_minimum(entry) == NEXT_RELEASE


def test_sqlite_apply_is_idempotent_and_refuses_leftover_values() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE session_launches ("
        "launch_id TEXT PRIMARY KEY, "
        "origin TEXT NOT NULL DEFAULT 'operator')"
    )
    conn.execute(
        "INSERT INTO session_launches VALUES ('launch-1', ?)",
        (LAUNCH_ORIGIN_OPERATOR,),
    )

    entry.apply(conn)
    entry.apply(conn)
    entry.invariants(conn)

    conn.execute(
        "INSERT INTO session_launches VALUES ('launch-2', ?)",
        (LAUNCH_ORIGIN_STEERING,),
    )
    leftover = sqlite3.connect(":memory:")
    leftover.execute(
        "CREATE TABLE session_launches ("
        "launch_id TEXT PRIMARY KEY, origin TEXT NOT NULL)"
    )
    leftover.execute(
        "INSERT INTO session_launches VALUES ('stale', 'steering_backstop')"
    )
    with pytest.raises(AssertionError, match="unsupported values"):
        entry.apply(leftover)


@pytest.fixture
def origin_db():
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    conn.execute(
        """
        CREATE TABLE session_launches (
            launch_id TEXT PRIMARY KEY,
            origin TEXT NOT NULL DEFAULT 'operator'
                CHECK(origin IN ('operator'))
        )
        """
    )
    conn.execute(
        "INSERT INTO session_launches VALUES ('launch-1', %s)",
        (LAUNCH_ORIGIN_OPERATOR,),
    )
    conn.commit()
    try:
        yield conn
    finally:
        conn.close()
        pg_testdb.drop_test_database(name)


def test_postgres_check_rewrite_admits_steering_and_is_idempotent(origin_db) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        origin_db.execute(
            "INSERT INTO session_launches VALUES ('blocked', %s)",
            (LAUNCH_ORIGIN_STEERING,),
        )
    origin_db.rollback()

    entry.apply(origin_db)
    entry.apply(origin_db)
    entry.invariants(origin_db)
    origin_db.commit()

    origin_db.execute(
        "INSERT INTO session_launches VALUES ('launch-2', %s)",
        (LAUNCH_ORIGIN_STEERING,),
    )
    origin_db.commit()
    with pytest.raises(psycopg.errors.CheckViolation):
        origin_db.execute(
            "INSERT INTO session_launches VALUES ('invented', 'invented-origin')"
        )
    origin_db.rollback()
