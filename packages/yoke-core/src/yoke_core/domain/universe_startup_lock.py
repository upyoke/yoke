"""Database advisory lock separating server startup from universe import."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg

from yoke_core.domain import db_backend


# Stable signed-bigint advisory-lock namespace for the one-universe database.
UNIVERSE_STARTUP_LOCK_ID = 0x596F6B65496D7074


class UniverseStartupBusy(RuntimeError):
    """A server startup currently owns the universe database boundary."""


def _connection(dsn: str) -> psycopg.Connection:
    return db_backend.connect_psycopg(dsn, autocommit=True)


@contextmanager
def server_startup_guard(dsn: str) -> Iterator[None]:
    """Hold a shared lock while a server inspects and prepares its universe."""
    conn = _connection(dsn)
    try:
        conn.execute(
            "SELECT pg_advisory_lock_shared(%s)",
            (UNIVERSE_STARTUP_LOCK_ID,),
        )
        try:
            yield
        finally:
            conn.execute(
                "SELECT pg_advisory_unlock_shared(%s)",
                (UNIVERSE_STARTUP_LOCK_ID,),
            )
    finally:
        conn.close()


@contextmanager
def exclusive_import_guard(dsn: str) -> Iterator[None]:
    """Fail fast if any server is preparing the DB; otherwise exclude one."""
    conn = _connection(dsn)
    acquired = False
    try:
        row = conn.execute(
            "SELECT pg_try_advisory_lock(%s)",
            (UNIVERSE_STARTUP_LOCK_ID,),
        ).fetchone()
        acquired = bool(row and row[0])
        if not acquired:
            raise UniverseStartupBusy(
                "the self-host database is being prepared by a core service; "
                "stop core and retry the import"
            )
        yield
    finally:
        if acquired:
            conn.execute(
                "SELECT pg_advisory_unlock(%s)",
                (UNIVERSE_STARTUP_LOCK_ID,),
            )
        conn.close()


__all__ = [
    "UNIVERSE_STARTUP_LOCK_ID",
    "UniverseStartupBusy",
    "exclusive_import_guard",
    "server_startup_guard",
]
