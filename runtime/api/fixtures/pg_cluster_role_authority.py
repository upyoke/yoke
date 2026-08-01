"""Serialization for tests that mutate cluster-global PostgreSQL roles.

Disposable databases isolate schema and data, but roles belong to the
whole cluster: a temporary role one xdist worker creates is visible to
every other worker, and a worker taking an inventory of privileged roles
will see it. Those tests therefore need exclusion from each other — but
only from each other, not from the entire suite.

A single advisory lock on the maintenance database provides exactly that:
every cooperating test takes the same lock, so they run one at a time
while every unrelated test stays parallel.
"""

from __future__ import annotations

import contextlib

import psycopg

# Session-level advisory locks are scoped to a database. All cooperating role
# tests acquire this key through the shared ``postgres`` maintenance database.
_LOCK_ID = 0x596F6B65526F6C65


@contextlib.contextmanager
def cluster_role_authority():
    """Hold the cluster-wide role authority for the duration of the block."""
    from runtime.api.fixtures import pg_testdb

    with psycopg.connect(
        pg_testdb.maintenance_dsn(), autocommit=True
    ) as authority:
        authority.execute("SELECT pg_advisory_lock(%s)", (_LOCK_ID,))
        try:
            yield
        finally:
            unlocked = authority.execute(
                "SELECT pg_advisory_unlock(%s)", (_LOCK_ID,)
            ).fetchone()
            if unlocked != (True,):
                raise RuntimeError(
                    "PostgreSQL cluster-role test authority was not held"
                )


__all__ = ["cluster_role_authority"]
