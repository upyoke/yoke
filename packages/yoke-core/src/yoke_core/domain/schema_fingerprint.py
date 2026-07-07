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
from typing import Optional, Union

import psycopg

from yoke_core.domain.db_helpers import iso8601_now
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
        db_path, surface="schema_fingerprint sqlite_file target",
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
                str(db_path), surface="schema_fingerprint sqlite_file connection",
            )


def _fingerprint_postgres_conn(conn) -> str:
    """Compute the canonical fingerprint over the current Postgres schema."""
    rows = conn.execute(
        """
        WITH objects AS (
            SELECT
                'table' AS object_type,
                cls.relname AS object_name,
                string_agg(
                    att.attname || ':' ||
                    pg_catalog.format_type(att.atttypid, att.atttypmod) || ':' ||
                    COALESCE(
                        pg_catalog.pg_get_expr(def.adbin, def.adrelid),
                        ''
                    ) || ':' ||
                    CASE WHEN att.attnotnull THEN 'NO' ELSE 'YES' END,
                    chr(10) ORDER BY att.attnum
                ) AS definition
            FROM pg_catalog.pg_class cls
            JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace
            JOIN pg_catalog.pg_attribute att ON att.attrelid = cls.oid
            LEFT JOIN pg_catalog.pg_attrdef def
              ON def.adrelid = att.attrelid AND def.adnum = att.attnum
            WHERE ns.nspname = current_schema()
              AND cls.relkind IN ('r', 'p')
              AND att.attnum > 0
              AND NOT att.attisdropped
            GROUP BY cls.oid, cls.relname

            UNION ALL

            SELECT
                'view' AS object_type,
                cls.relname AS object_name,
                COALESCE(pg_catalog.pg_get_viewdef(cls.oid, true), '') AS definition
            FROM pg_catalog.pg_class cls
            JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace
            WHERE ns.nspname = current_schema()
              AND cls.relkind IN ('v', 'm')

            UNION ALL

            SELECT
                'index' AS object_type,
                idx.relname AS object_name,
                pg_catalog.pg_get_indexdef(idx.oid) AS definition
            FROM pg_catalog.pg_index ind
            JOIN pg_catalog.pg_class idx ON idx.oid = ind.indexrelid
            JOIN pg_catalog.pg_class tbl ON tbl.oid = ind.indrelid
            JOIN pg_catalog.pg_namespace ns ON ns.oid = tbl.relnamespace
            WHERE ns.nspname = current_schema()

            UNION ALL

            SELECT
                'constraint' AS object_type,
                con.conname AS object_name,
                cls.relname || ':' ||
                    pg_catalog.pg_get_constraintdef(con.oid) AS definition
            FROM pg_catalog.pg_constraint con
            JOIN pg_catalog.pg_class cls ON cls.oid = con.conrelid
            JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace
            WHERE ns.nspname = current_schema()
        )
        SELECT object_type, object_name, COALESCE(definition, '')
        FROM objects
        ORDER BY object_type, object_name, definition
        """
    ).fetchall()
    return _hash_rows(rows)


def _fingerprint_postgres_target(target) -> str:
    if hasattr(target, "execute"):
        return _fingerprint_postgres_conn(target)

    conn = psycopg.connect(str(target))
    try:
        return _fingerprint_postgres_conn(conn)
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


def _parse_iso(raw: str) -> datetime:
    """Parse a UTC ISO-8601 timestamp ending in either ``Z`` or ``+HH:MM``.

    ``db_helpers.iso8601_now`` emits the ``Z`` shape; we normalize both
    accepted forms to ``datetime.fromisoformat``-compatible text before
    parsing so the comparison is timezone-aware.
    """
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def freshness_expired(
    rehearsed_at: Optional[str],
    *,
    now: Optional[str] = None,
    window_minutes: int = FRESHNESS_WINDOW_MINUTES,
) -> bool:
    """Return ``True`` when the 30-min rehearsal-freshness window has elapsed.

    A missing / empty / malformed ``rehearsed_at`` is treated as expired
    — the live-apply path refuses to run a rehearsal whose timestamp
    cannot be interpreted, so the conservative answer is "expired".
    ``now`` defaults to :func:`iso8601_now` so tests can pin time.
    """
    if not rehearsed_at:
        return True
    now_iso = now or iso8601_now()
    try:
        r = _parse_iso(rehearsed_at)
        n = _parse_iso(now_iso)
    except (ValueError, TypeError):
        return True
    return (n - r) > timedelta(minutes=window_minutes)


__all__ = [
    "FRESHNESS_WINDOW_MINUTES",
    "SUPPORTED_KINDS",
    "UnsupportedFingerprintKindError",
    "fingerprint_kind",
    "freshness_expired",
]
