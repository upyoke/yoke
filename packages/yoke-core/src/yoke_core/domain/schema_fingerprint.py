"""Backend-portable schema fingerprint for governed DB mutations.

The two-unit apply contract freezes a rehearsal by capturing the
target schema fingerprint at the end of the rehearsal unit and re-checking it
at the start of the live-apply unit. Pairing the
fingerprint equality check with a 30-minute freshness window on
``rehearsed_at`` guarantees that live apply only runs against the same
shape of schema the rehearsal exercised, and only for as long as the
operator's attention on that rehearsal is plausibly fresh.

The helper is backend-portable by construction: dispatch is keyed by the
explicit schema target kind and each reader abstracts over that backend's
schema-introspection surface. SQLite support is limited to explicit external
validation/import files; root ``data/yoke.db`` is rejected here because it is
not a live Yoke authority. Callers never concatenate backend-specific SQL
strings outside this module — the fingerprint IS the abstraction boundary.

Usage::

    from yoke_core.domain.schema_fingerprint import (
        fingerprint_kind, freshness_expired,
    )

    fp = fingerprint_kind("postgres", conn)
    # ... rehearse ...
    if fingerprint_kind("postgres", conn) != fp:
        raise SchemaDrifted()
    if freshness_expired(rehearsed_at):
        raise RehearsalStale()
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta
from typing import Union

import psycopg

from yoke_contracts.timestamps import InvalidInstant, parse_instant, utc_now
from yoke_core.domain.schema_fingerprint_postgres_rows import _postgres_schema_rows
from yoke_core.domain.sqlite_validation_boundary import (
    reject_retired_root_yoke_db_path,
)


FRESHNESS_WINDOW_MINUTES = 30

SUPPORTED_KINDS = frozenset({"postgres", "sqlite_file"})


class UnsupportedFingerprintKindError(ValueError):
    """Raised when a backend kind is not yet wired for fingerprinting."""


# ---------------------------------------------------------------------------
# Backend fingerprinting
# ---------------------------------------------------------------------------


def _fingerprint_generic_sqlite_validation_conn(conn: sqlite3.Connection) -> str:
    """Compute the canonical fingerprint over a SQLite connection.

    This branch is the generic ``sqlite_file`` fingerprint boundary, not a
    Yoke authority reader; active control-plane callers use ``kind="postgres"``.
    Reads ``(type, name, sql)`` from ``sqlite_master`` excluding internal
    ``sqlite_%``-prefixed rows, orders deterministically by ``(type, name)``,
    and SHA256-hashes a NUL-delimited join. The NUL delimiter ensures no legal
    SQL fragment can collide with the separator, so identical hashes imply
    identical canonical schema dumps.
    """
    _reject_retired_root_yoke_db_conn(conn)
    rows = conn.execute(
        "SELECT type, name, COALESCE(sql, '') FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()
    return _hash_rows(rows)


def _fingerprint_generic_sqlite_validation_path(db_path: str) -> str:
    reject_retired_root_yoke_db_path(
        db_path,
        surface="schema_fingerprint sqlite_file target",
    )
    conn = sqlite3.connect(db_path)
    try:
        return _fingerprint_generic_sqlite_validation_conn(conn)
    finally:
        conn.close()


def _hash_rows(rows) -> str:
    hasher = hashlib.sha256()
    for r_type, r_name, r_sql in rows:
        hasher.update(str(r_type).encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(str(r_name).encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(str(r_sql).encode("utf-8"))
        hasher.update(b"\x00")
    return hasher.hexdigest()


def _reject_retired_root_yoke_db_conn(conn: sqlite3.Connection) -> None:
    """Refuse open SQLite connections attached to root ``data/yoke.db``."""
    rows = conn.execute("PRAGMA database_list").fetchall()
    for row in rows:
        db_path = row[2] if len(row) > 2 else ""
        if db_path:
            reject_retired_root_yoke_db_path(
                str(db_path),
                surface="schema_fingerprint sqlite_file connection",
            )


def _fingerprint_postgres_conn(conn) -> str:
    """Compute the canonical fingerprint over the current Postgres schema."""
    return _hash_rows(_postgres_schema_rows(conn))


def _fingerprint_postgres_target(target) -> str:
    if hasattr(target, "execute"):
        return _fingerprint_postgres_conn(target)

    conn = psycopg.connect(str(target))
    try:
        return _fingerprint_postgres_conn(conn)
    finally:
        conn.close()


def fingerprint_portable_postgres_schema(target) -> str:
    """Fingerprint Postgres structure for name-mapped archive restore.

    Physical table-column order is excluded because portable restore binds
    every value to a named target column. All column properties and every
    other schema object remain part of the exact comparison.
    """
    if hasattr(target, "execute"):
        return _hash_rows(
            _postgres_schema_rows(target, order_table_columns_by_name=True)
        )

    conn = psycopg.connect(str(target))
    try:
        return _hash_rows(_postgres_schema_rows(conn, order_table_columns_by_name=True))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Public dispatch
# ---------------------------------------------------------------------------


def fingerprint_kind(
    kind: str,
    target: Union[str, sqlite3.Connection],
) -> str:
    """Backend-portable dispatch by explicit schema target kind.

    *target* is a filesystem path or an open ``sqlite3.Connection`` for
    ``sqlite_file``; for ``postgres`` it is a DSN string or an open connection.

    Raises :class:`UnsupportedFingerprintKindError` for any unsupported kind,
    mirroring the "combination not yet supported" posture of the
    capability validator so callers can surface the same structured
    error to the operator.
    """
    if kind == "sqlite_file":
        if isinstance(target, sqlite3.Connection):
            return _fingerprint_generic_sqlite_validation_conn(target)
        return _fingerprint_generic_sqlite_validation_path(str(target))
    if kind == "postgres":
        return _fingerprint_postgres_target(target)
    raise UnsupportedFingerprintKindError(
        f"schema fingerprint kind {kind!r} is not yet wired for fingerprinting"
    )


# ---------------------------------------------------------------------------
# Freshness window
# ---------------------------------------------------------------------------


def freshness_expired(
    rehearsed_at: datetime | str | None,
    *,
    now: datetime | str | None = None,
    window_minutes: int = FRESHNESS_WINDOW_MINUTES,
) -> bool:
    """Refuse stale or invalid rehearsal evidence using native instant age.

    Missing or invalid rehearsal evidence is expired. An explicit ``now``
    must be an aware instant; only None selects the native current clock.
    """
    current = utc_now() if now is None else parse_instant(now)
    if rehearsed_at is None:
        return True
    try:
        rehearsed = parse_instant(rehearsed_at)
    except InvalidInstant:
        return True
    return current - rehearsed > timedelta(minutes=window_minutes)


__all__ = [
    "FRESHNESS_WINDOW_MINUTES",
    "SUPPORTED_KINDS",
    "UnsupportedFingerprintKindError",
    "fingerprint_kind",
    "fingerprint_portable_postgres_schema",
    "freshness_expired",
]
