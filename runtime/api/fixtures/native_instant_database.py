"""Isolated blank PostgreSQL databases for native instant conversion checks."""

from contextlib import contextmanager


@contextmanager
def blank_database():
    from runtime.api.fixtures.pg_testdb import (
        connect_test_database,
        create_test_database,
        drop_test_database,
    )

    name = create_test_database()
    conn = connect_test_database(name)
    try:
        yield conn
    finally:
        conn.close()
        drop_test_database(name)
