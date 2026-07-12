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


def _postgres_schema_rows(
    conn,
    *,
    order_table_columns_by_name: bool = False,
) -> list[tuple[str, str, str]]:
    """Canonical Postgres schema rows for exact or name-mapped comparison."""
    table_column_order = (
        'att.attname COLLATE "C"' if order_table_columns_by_name else "att.attnum"
    )
    query = """
        WITH objects AS (
            SELECT
                'table' AS object_type,
                cls.relname AS object_name,
                cls.relkind::text || ':' || cls.relpersistence::text || ':' ||
                COALESCE(am.amname, '') || ':' ||
                cls.relrowsecurity::text || ':' ||
                cls.relforcerowsecurity::text || ':' ||
                COALESCE(
                    (
                        SELECT string_agg(option, ',' ORDER BY option)
                        FROM unnest(cls.reloptions) AS option
                    ),
                    ''
                ) || chr(10) ||
                string_agg(
                    att.attname || ':' ||
                    pg_catalog.format_type(att.atttypid, att.atttypmod) || ':' ||
                    COALESCE(
                        CASE WHEN att.attcollation = 0 THEN '' ELSE
                            coll_ns.nspname || '.' || coll.collname
                        END,
                        ''
                    ) || ':' ||
                    COALESCE(
                        pg_catalog.pg_get_expr(def.adbin, def.adrelid),
                        ''
                    ) || ':' ||
                    CASE WHEN att.attnotnull THEN 'NO' ELSE 'YES' END || ':' ||
                    att.attidentity::text || ':' || att.attgenerated::text || ':' ||
                    COALESCE(
                        pg_catalog.pg_get_serial_sequence(
                            pg_catalog.quote_ident(ns.nspname) || '.' ||
                                pg_catalog.quote_ident(cls.relname),
                            att.attname
                        ),
                        ''
                    ),
                    chr(10) ORDER BY __TABLE_COLUMN_ORDER__
                ) AS definition
            FROM pg_catalog.pg_class cls
            JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace
            JOIN pg_catalog.pg_attribute att ON att.attrelid = cls.oid
            LEFT JOIN pg_catalog.pg_am am ON am.oid = cls.relam
            LEFT JOIN pg_catalog.pg_collation coll ON coll.oid = att.attcollation
            LEFT JOIN pg_catalog.pg_namespace coll_ns ON coll_ns.oid = coll.collnamespace
            LEFT JOIN pg_catalog.pg_attrdef def
              ON def.adrelid = att.attrelid AND def.adnum = att.attnum
            WHERE ns.nspname = current_schema()
              AND cls.relkind IN ('r', 'p')
              AND att.attnum > 0
              AND NOT att.attisdropped
            GROUP BY cls.oid, cls.relname, am.amname

            UNION ALL

            SELECT
                'sequence' AS object_type,
                cls.relname AS object_name,
                pg_catalog.format_type(seq.seqtypid, NULL) || ':' ||
                    seq.seqstart || ':' || seq.seqincrement || ':' ||
                    seq.seqmax || ':' || seq.seqmin || ':' ||
                    seq.seqcache || ':' || seq.seqcycle AS definition
            FROM pg_catalog.pg_sequence seq
            JOIN pg_catalog.pg_class cls ON cls.oid = seq.seqrelid
            JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace
            WHERE ns.nspname = current_schema()

            UNION ALL

            SELECT
                'view' AS object_type,
                cls.relname AS object_name,
                COALESCE(
                    (
                        SELECT string_agg(option, ',' ORDER BY option)
                        FROM unnest(cls.reloptions) AS option
                    ),
                    ''
                ) || chr(10) ||
                COALESCE(pg_catalog.pg_get_viewdef(cls.oid, true), '') AS definition
            FROM pg_catalog.pg_class cls
            JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace
            WHERE ns.nspname = current_schema()
              AND cls.relkind IN ('v', 'm')

            UNION ALL

            SELECT
                'function' AS object_type,
                proc.proname || '(' ||
                    pg_catalog.pg_get_function_identity_arguments(proc.oid) || ')'
                    AS object_name,
                pg_catalog.pg_get_functiondef(proc.oid) AS definition
            FROM pg_catalog.pg_proc proc
            JOIN pg_catalog.pg_namespace ns ON ns.oid = proc.pronamespace
            WHERE ns.nspname = current_schema()
              AND proc.prokind IN ('f', 'p')

            UNION ALL

            SELECT
                'trigger' AS object_type,
                cls.relname || '.' || trig.tgname AS object_name,
                trig.tgenabled::text || ':' ||
                    pg_catalog.pg_get_triggerdef(trig.oid, true) AS definition
            FROM pg_catalog.pg_trigger trig
            JOIN pg_catalog.pg_class cls ON cls.oid = trig.tgrelid
            JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace
            WHERE ns.nspname = current_schema()
              AND NOT trig.tgisinternal

            UNION ALL

            SELECT
                'rule' AS object_type,
                cls.relname || '.' || rewrite.rulename AS object_name,
                pg_catalog.pg_get_ruledef(rewrite.oid, true) AS definition
            FROM pg_catalog.pg_rewrite rewrite
            JOIN pg_catalog.pg_class cls ON cls.oid = rewrite.ev_class
            JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace
            WHERE ns.nspname = current_schema()
              AND rewrite.rulename <> '_RETURN'

            UNION ALL

            SELECT
                'policy' AS object_type,
                cls.relname || '.' || policy.polname AS object_name,
                policy.polcmd::text || ':' || policy.polpermissive::text || ':' ||
                    COALESCE(
                        (
                            SELECT string_agg(
                                CASE WHEN role_oid = 0 THEN 'PUBLIC'
                                    ELSE pg_catalog.pg_get_userbyid(role_oid)
                                END,
                                ',' ORDER BY role_oid
                            )
                            FROM unnest(policy.polroles) AS role_oid
                        ),
                        ''
                    ) || ':' ||
                    COALESCE(pg_catalog.pg_get_expr(policy.polqual, policy.polrelid), '') || ':' ||
                    COALESCE(pg_catalog.pg_get_expr(policy.polwithcheck, policy.polrelid), '')
                    AS definition
            FROM pg_catalog.pg_policy policy
            JOIN pg_catalog.pg_class cls ON cls.oid = policy.polrelid
            JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace
            WHERE ns.nspname = current_schema()

            UNION ALL

            SELECT
                'index' AS object_type,
                idx.relname AS object_name,
                ind.indisvalid::text || ':' || ind.indisready::text || ':' ||
                    ind.indislive::text || ':' || ind.indcheckxmin::text || ':' ||
                    ind.indisreplident::text || ':' ||
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
                    con.convalidated::text || ':' ||
                    con.condeferrable::text || ':' ||
                    con.condeferred::text || ':' ||
                    pg_catalog.pg_get_constraintdef(con.oid) AS definition
            FROM pg_catalog.pg_constraint con
            JOIN pg_catalog.pg_class cls ON cls.oid = con.conrelid
            JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace
            WHERE ns.nspname = current_schema()
        )
        SELECT object_type, object_name, COALESCE(definition, '')
        FROM objects
        ORDER BY object_type, object_name, definition
        """.replace("__TABLE_COLUMN_ORDER__", table_column_order)
    rows = conn.execute(query).fetchall()
    return [tuple(str(value) for value in row) for row in rows]


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
        return _hash_rows(
            _postgres_schema_rows(conn, order_table_columns_by_name=True)
        )
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
    "fingerprint_portable_postgres_schema",
    "freshness_expired",
]
