"""Archive admission estimates live table data without heap bloat or indexes."""

import psycopg
import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain.universe_artifact_transfer import estimate_universe


@pytest.fixture
def database():
    name = pg_testdb.create_test_database()
    dsn = pg_testdb.dsn_for_test_database(name)
    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            yield conn, dsn
    finally:
        pg_testdb.drop_test_database(name)


def _estimate(dsn):
    result = estimate_universe(dsn=dsn, exclude_artifacts=True)
    assert result["estimated_bytes"] == result["estimated_dump_bytes"]
    assert result["artifact_bytes"] == 0
    return result["estimated_dump_bytes"]


def test_pruning_reduces_estimate_without_shrinking_database(database):
    conn, dsn = database
    conn.execute(
        "CREATE TABLE entries (id integer PRIMARY KEY, payload text) "
        "WITH (autovacuum_enabled=false)"
    )
    conn.execute(
        "INSERT INTO entries SELECT i, repeat('x', 512) "
        "FROM generate_series(1, 20000) i"
    )
    conn.execute("ANALYZE entries")
    before = _estimate(dsn)
    physical_before = conn.execute(
        "SELECT pg_database_size(current_database())"
    ).fetchone()[0]
    # Keep rows on every page, including the last, so VACUUM cannot truncate it.
    conn.execute("DELETE FROM entries WHERE id % 10 <> 0")
    conn.execute("VACUUM ANALYZE entries")
    after = _estimate(dsn)
    physical_after = conn.execute(
        "SELECT pg_database_size(current_database())"
    ).fetchone()[0]
    assert before > 10_000_000
    assert after <= before * 0.2
    assert physical_after >= physical_before * 0.95


@pytest.mark.parametrize("analyze", [False, True])
def test_missing_statistics_uses_table_size_without_indexes(database, analyze):
    conn, dsn = database
    conn.execute(
        "CREATE TABLE entries (id integer PRIMARY KEY) "
        "WITH (autovacuum_enabled=false)"
    )
    conn.execute("ALTER TABLE entries ALTER COLUMN id SET STATISTICS 0")
    conn.execute("INSERT INTO entries SELECT generate_series(1, 10000)")
    if analyze:
        conn.execute("ANALYZE entries")
    assert conn.execute(
        "SELECT count(*) FROM pg_stats WHERE tablename='entries'"
    ).fetchone()[0] == 0
    reltuples, table_bytes, total_bytes = conn.execute(
        "SELECT reltuples, pg_table_size(oid), pg_total_relation_size(oid) "
        "FROM pg_class WHERE oid='entries'::regclass"
    ).fetchone()
    assert (reltuples >= 0) is analyze
    assert _estimate(dsn) == table_bytes
    assert total_bytes > table_bytes


def test_toast_storage_is_included_without_indexes(database):
    conn, dsn = database
    conn.execute("CREATE TABLE entries (id integer PRIMARY KEY, payload text)")
    conn.execute(
        "INSERT INTO entries SELECT i, "
        "(SELECT string_agg(md5(i::text || ':' || j::text), '') "
        "FROM generate_series(1, 128) j) FROM generate_series(1, 100) i"
    )
    conn.execute("ANALYZE entries")
    rows, toast_bytes = conn.execute(
        "SELECT reltuples, pg_table_size(reltoastrelid) FROM pg_class "
        "WHERE oid='entries'::regclass"
    ).fetchone()
    width = conn.execute(
        "SELECT sum(avg_width) FROM pg_stats "
        "WHERE schemaname='public' AND tablename='entries' AND NOT inherited"
    ).fetchone()[0]
    assert toast_bytes > 100_000
    assert _estimate(dsn) == int(rows * width + toast_bytes)


def test_partition_rows_are_counted_once_across_user_schemas(database):
    conn, dsn = database
    conn.execute('CREATE SCHEMA "pgdata"')
    conn.execute(
        'CREATE TABLE "pgdata".entries (id integer) PARTITION BY RANGE (id)'
    )
    conn.execute(
        'CREATE TABLE "pgdata".entries_low PARTITION OF "pgdata".entries '
        "FOR VALUES FROM (0) TO (100)"
    )
    conn.execute('INSERT INTO "pgdata".entries SELECT generate_series(1, 99)')
    conn.execute('ANALYZE "pgdata".entries')
    assert _estimate(dsn) == 99 * 4


def test_empty_database_has_zero_estimated_dump_bytes(database):
    _, dsn = database
    assert _estimate(dsn) == 0
