"""Report-local SQL reuse preserves independent cursors and live boundaries."""

import sqlite3

from yoke_core.domain.steering_report_read_connection import ReportReadConnection


def test_reads_share_one_query_and_independent_cursors():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE facts (value INTEGER)")
    conn.executemany("INSERT INTO facts VALUES (?)", [(1,), (2,)])
    queries = []
    conn.set_trace_callback(queries.append)
    report = ReportReadConnection(conn)
    first = report.execute("SELECT value FROM facts")
    assert first.fetchone() == (1,)
    assert report.execute("SELECT value FROM facts").fetchall() == [(1,), (2,)]
    assert first.fetchall() == [(2,)]
    assert len(queries) == 1
    ReportReadConnection(conn).execute("SELECT value FROM facts").fetchall()
    assert len(queries) == 2


def test_mutation_and_rollback_invalidate_rows():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE facts (value INTEGER)")
    conn.commit()
    report = ReportReadConnection(conn)
    assert report.execute("SELECT value FROM facts").fetchall() == []
    report.execute("INSERT INTO facts VALUES (?)", (3,))
    assert report.execute("SELECT value FROM facts").fetchone() == (3,)
    report.rollback()
    assert report.execute("SELECT value FROM facts").fetchall() == []


def test_multiline_select_and_read_only_savepoints_preserve_reuse():
    conn = sqlite3.connect(":memory:")
    queries = []
    conn.set_trace_callback(queries.append)
    report = ReportReadConnection(conn)
    sql = "SELECT\n  3 AS value"
    assert report.execute(sql).fetchone() == (3,)
    report.execute("SAVEPOINT read_block")
    assert report.execute(sql).fetchone() == (3,)
    report.execute("RELEASE SAVEPOINT read_block")
    assert report.execute(sql).fetchone() == (3,)
    assert queries.count(sql) == 1
    report.execute("SAVEPOINT rollback_block")
    report.execute("ROLLBACK TO SAVEPOINT rollback_block")
    assert report.execute(sql).fetchone() == (3,)
    assert queries.count(sql) == 2


def test_writes_inside_a_savepoint_and_commit_refresh_rows():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE facts (value INTEGER)")
    conn.commit()
    report = ReportReadConnection(conn)
    sql = "SELECT value FROM facts"
    assert report.execute(sql).fetchall() == []
    report.execute("SAVEPOINT writing")
    report.execute("INSERT INTO facts VALUES (4)")
    report.execute("RELEASE SAVEPOINT writing")
    assert report.execute(sql).fetchall() == [(4,)]
    report.commit()
    conn.execute("INSERT INTO facts VALUES (5)")
    assert report.execute(sql).fetchall() == [(4,), (5,)]
