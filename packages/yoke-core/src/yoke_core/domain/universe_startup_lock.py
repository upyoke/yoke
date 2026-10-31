"""Database advisory lock separating server startup from universe import."""

from __future__ import annotations

import os
import hashlib
from collections.abc import Mapping
from contextlib import contextmanager
from typing import Iterator

import psycopg

from yoke_core.domain import db_backend, universe_source_pause


# Stable signed-bigint advisory-lock namespace for the one-universe database.
UNIVERSE_STARTUP_LOCK_ID = 0x596F6B65496D7074
STARTUP_LOCK_APPLICATION = "yoke-universe-startup-lock"

# Existing hosted-container env contract (compose injects the DSN path
# and bind). The environment name is not part of the proof.
HOSTED_TENANT_DSN_FILE = "/run/yoke/dsn"
HOSTED_TENANT_API_HOST = "0.0.0.0"
HOSTED_TENANT_API_PORT = "8000"


class UniverseStartupBusy(RuntimeError):
    """A server startup currently owns the universe database boundary."""


def hosted_tenant_container_process(
    env: Mapping[str, str] | None = None,
) -> bool:
    """True only for the proven hosted tenant-container env conjunction."""
    source = os.environ if env is None else env
    return (
        source.get("YOKE_PG_DSN_FILE") == HOSTED_TENANT_DSN_FILE
        and source.get("YOKE_API_HOST") == HOSTED_TENANT_API_HOST
        and source.get("YOKE_API_PORT") == HOSTED_TENANT_API_PORT
    )


def _connection(dsn: str) -> psycopg.Connection:
    return db_backend.connect_psycopg(dsn, autocommit=True)


def _lock_target(dsn):
    if hosted_tenant_container_process():
        return dsn, UNIVERSE_STARTUP_LOCK_ID
    from psycopg.conninfo import conninfo_to_dict
    from yoke_core.domain.universe_database_pause import maintenance_dsn

    name = conninfo_to_dict(dsn)["dbname"]
    key = int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big") & (
        (1 << 63) - 1
    )
    return maintenance_dsn(dsn), key


def _server_connection(dsn: str):
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    options = conninfo_to_dict(dsn).get("options", "")
    readonly = make_conninfo(
        dsn,
        application_name=STARTUP_LOCK_APPLICATION,
        options=f"{options} -c default_transaction_read_only=on",
    )
    with universe_source_pause.pause_owner():
        return _connection(readonly)


@contextmanager
def server_startup_guard(dsn: str) -> Iterator[None]:
    """Hold a shared lock while a server inspects and prepares its universe."""
    with universe_source_pause.startup_access(dsn):
        target, lock_id = _lock_target(dsn)
        conn = _server_connection(target)
        try:
            conn.execute("SELECT pg_advisory_lock_shared(%s)", (lock_id,))
        except BaseException:
            conn.close()
            raise
    try:
        try:
            yield
        finally:
            conn.execute(
                "SELECT pg_advisory_unlock_shared(%s)",
                (lock_id,),
            )
    finally:
        conn.close()


@contextmanager
def exclusive_import_guard(dsn: str) -> Iterator[None]:
    """Fail fast if any server is preparing the DB; otherwise exclude one."""
    target, lock_id = _lock_target(dsn)
    conn = _connection(target)
    acquired = False
    try:
        row = conn.execute(
            "SELECT pg_try_advisory_lock(%s)",
            (lock_id,),
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
                (lock_id,),
            )
        conn.close()


__all__ = [
    "HOSTED_TENANT_API_HOST",
    "HOSTED_TENANT_API_PORT",
    "HOSTED_TENANT_DSN_FILE",
    "UNIVERSE_STARTUP_LOCK_ID",
    "UniverseStartupBusy",
    "exclusive_import_guard",
    "hosted_tenant_container_process",
    "server_startup_guard",
]
