"""Tests for the pooled blank test databases."""

from __future__ import annotations

import psycopg
import pytest

from runtime.api.fixtures import pg_blank_db_pool, pg_testdb


def _connect(name: str):
    return psycopg.connect(
        pg_testdb.dsn_for_test_database(name), autocommit=True
    )


def _database_exists(name: str) -> bool:
    with psycopg.connect(pg_testdb.maintenance_dsn(), autocommit=True) as admin:
        (count,) = admin.execute(
            "SELECT count(*) FROM pg_database WHERE datname = %s", (name,)
        ).fetchone()
    return count == 1


def _public_table_names(name: str) -> list[str]:
    conn = _connect(name)
    try:
        return [
            row[0]
            for row in conn.execute(
                "SELECT c.relname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind = 'r' "
                "ORDER BY 1"
            ).fetchall()
        ]
    finally:
        conn.close()


def test_released_database_is_reused_and_empty():
    first = pg_blank_db_pool.checkout()
    conn = _connect(first)
    try:
        conn.execute("CREATE TABLE leftovers (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO leftovers VALUES (1)")
    finally:
        conn.close()

    assert pg_blank_db_pool.release(first) is True

    second = pg_blank_db_pool.checkout()
    try:
        assert second == first
        assert _public_table_names(second) == []
    finally:
        pg_blank_db_pool.release(second)


def test_concurrent_checkouts_are_distinct_databases():
    first = pg_blank_db_pool.checkout()
    second = pg_blank_db_pool.checkout()
    try:
        assert first != second
    finally:
        pg_blank_db_pool.release(first)
        pg_blank_db_pool.release(second)


def test_release_drops_schemas_the_test_created():
    name = pg_blank_db_pool.checkout()
    conn = _connect(name)
    try:
        conn.execute("CREATE SCHEMA sidecar")
        conn.execute("CREATE TABLE sidecar.rows (id INTEGER)")
        conn.execute("CREATE VIEW public.rows_view AS SELECT 1 AS one")
        conn.execute("CREATE SEQUENCE public.counter")
    finally:
        conn.close()

    assert pg_blank_db_pool.release(name) is True

    reused = pg_blank_db_pool.checkout()
    try:
        assert reused == name
        conn = _connect(reused)
        try:
            (schemas,) = conn.execute(
                "SELECT count(*) FROM pg_namespace WHERE nspname = 'sidecar'"
            ).fetchone()
            (relations,) = conn.execute(
                "SELECT count(*) FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' "
                "AND c.relkind IN ('r','p','f','v','m','S')"
            ).fetchone()
        finally:
            conn.close()
        assert schemas == 0
        assert relations == 0
    finally:
        pg_blank_db_pool.release(reused)


def test_database_level_grant_retires_instead_of_pooling():
    name = pg_blank_db_pool.checkout()
    conn = _connect(name)
    try:
        # Any explicit grant or revoke on the database itself materializes
        # datacl, which a freshly created database does not have.
        conn.execute(f'REVOKE CONNECT ON DATABASE "{name}" FROM PUBLIC')
    finally:
        conn.close()

    assert pg_blank_db_pool.release(name) is False
    assert name not in pg_blank_db_pool._pooled

    # The caller now owns the drop, exactly as before pooling existed.
    pg_testdb.drop_test_database(name)
    assert _database_exists(name) is False


def test_leftover_routine_retires_instead_of_pooling():
    name = pg_blank_db_pool.checkout()
    conn = _connect(name)
    try:
        conn.execute(
            "CREATE FUNCTION public.leftover() RETURNS integer "
            "AS $$ SELECT 1 $$ LANGUAGE sql"
        )
    finally:
        conn.close()

    assert pg_blank_db_pool.release(name) is False
    pg_testdb.drop_test_database(name)
    assert _database_exists(name) is False


def test_release_terminates_connections_left_open():
    name = pg_blank_db_pool.checkout()
    leaked = _connect(name)
    try:
        leaked.execute("CREATE TABLE held (id INTEGER)")

        assert pg_blank_db_pool.release(name) is True

        with pytest.raises(psycopg.OperationalError):
            leaked.execute("SELECT 1")
    finally:
        leaked.close()
        reused = pg_blank_db_pool.checkout()
        assert _public_table_names(reused) == []
        pg_blank_db_pool.release(reused)


def test_release_ignores_databases_it_does_not_own():
    name = pg_testdb.create_test_database(pooled=False)
    try:
        assert pg_blank_db_pool.release(name) is False
    finally:
        pg_testdb.drop_test_database(name, pooled=False)
    assert _database_exists(name) is False


def test_create_test_database_serves_from_the_pool():
    pooled = pg_blank_db_pool.checkout()
    pg_blank_db_pool.release(pooled)

    served = pg_testdb.create_test_database()
    try:
        assert served == pooled
    finally:
        pg_testdb.drop_test_database(served)

    # And the drop returned it rather than destroying it.
    assert _database_exists(served) is True


def test_pooling_can_be_disabled_for_bisecting(monkeypatch):
    monkeypatch.setenv(pg_blank_db_pool.DISABLE_ENV, "1")
    name = pg_testdb.create_test_database()
    try:
        assert name not in pg_blank_db_pool._pooled
    finally:
        pg_testdb.drop_test_database(name)
    assert _database_exists(name) is False


def test_templated_creates_never_come_from_the_pool():
    spare = pg_blank_db_pool.checkout()
    pg_blank_db_pool.release(spare)

    clone = pg_testdb.create_test_database(template="template1")
    try:
        assert clone != spare
        assert clone not in pg_blank_db_pool._pooled
    finally:
        pg_testdb.drop_test_database(clone)
