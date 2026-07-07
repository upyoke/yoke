"""Doctor test helpers minting disposable Postgres test databases."""

from __future__ import annotations

from runtime.api.fixtures import pg_testdb


def connect_disposable_test_db(*_args, **_kwargs):
    """Return a connection to a fresh disposable Postgres test database.

    Positional and keyword arguments are ignored compatibility slots
    (legacy callers passed file paths or ``":memory:"``). The backing
    database is dropped when the connection closes; a garbage-collection
    finalizer covers connections a test never closes explicitly.
    """
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    return pg_testdb.drop_database_on_close(conn, name)
