"""Trusted target and COPY grammar for portable universe restoration."""

from __future__ import annotations

import re
from typing import Sequence

from yoke_core.domain.universe_portability_common import (
    ArchiveCompatibilityError,
    ArchiveInvalidError,
)
from yoke_core.domain.universe_portability_content_contract import (
    ARCHIVE_COLUMN_RENAMES,
    ARCHIVE_OMITTABLE_TARGET_COLUMNS,
)


_SQL_IDENTIFIER = r'(?:(?:"(?:[^"]|"")*")|[a-z_][a-z0-9_$]*)'
COPY_HEADER_RE = re.compile(
    rf"^COPY (?P<schema>{_SQL_IDENTIFIER})\."
    rf"(?P<table>{_SQL_IDENTIFIER}) "
    rf"\((?P<columns>{_SQL_IDENTIFIER}(?:, {_SQL_IDENTIFIER})*)\) "
    r"FROM stdin;\r?\n$"
)
SETVAL_RE = re.compile(
    r"^SELECT pg_catalog\.setval\('public\.([a-z_][a-z0-9_]*)'"
    r"(?:::\w+)?\s*,\s*(-?\d+)\s*,\s*(true|false)\);\r?\n$"
)
RESTORE_SET_RE = re.compile(
    r"^SET (?:statement_timeout|lock_timeout|"
    r"idle_in_transaction_session_timeout|transaction_timeout|"
    r"client_encoding|standard_conforming_strings|check_function_bodies|"
    r"xmloption|client_min_messages|row_security|default_tablespace|"
    r"default_table_access_method) = [^;\r\n]*;\r?\n$"
)
RESTORE_RESTRICT_RE = re.compile(r"^\\(?:un)?restrict [^\s\r\n]+\r?\n$")
RESTORE_SEARCH_PATH = "SELECT pg_catalog.set_config('search_path', '', false);"

MIGRATION_LEDGER_TABLE = "applied_migrations"
MIGRATION_DIGEST_COLUMN = "content_sha256"
MIGRATION_EVIDENCE_TABLE = "migration_content_adoptions"


def unquote_identifier(value: str) -> str:
    if value.startswith('"'):
        return value[1:-1].replace('""', '"')
    return value


def restore_target_columns(conn: object) -> dict[str, tuple[str, ...]]:
    rows = conn.execute(  # type: ignore[attr-defined]
        "SELECT cls.relname, att.attname"
        " FROM pg_catalog.pg_class cls"
        " JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace"
        " JOIN pg_catalog.pg_attribute att ON att.attrelid = cls.oid"
        " WHERE ns.nspname = current_schema() AND cls.relkind = 'r'"
        " AND att.attnum > 0 AND NOT att.attisdropped AND att.attgenerated = ''"
        " ORDER BY cls.relname, att.attnum"
    ).fetchall()
    pending: dict[str, list[str]] = {}
    for table, column in rows:
        pending.setdefault(str(table), []).append(str(column))
    return {table: tuple(columns) for table, columns in pending.items()}


def restore_target_sequences(conn: object) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(  # type: ignore[attr-defined]
            "SELECT sequencename FROM pg_catalog.pg_sequences"
            " WHERE schemaname = current_schema()"
        ).fetchall()
    }


def compatible_restore_columns(
    table: str,
    archive_columns: Sequence[str],
    target_columns: Sequence[str],
) -> tuple[str, ...]:
    """Map one known historical COPY shape onto the trusted target table."""
    mapped = tuple(
        ARCHIVE_COLUMN_RENAMES.get((table, column), column)
        for column in archive_columns
    )
    target = set(target_columns)
    if len(mapped) != len(set(mapped)):
        raise ArchiveInvalidError(
            f"the universe archive COPY columns are invalid for {table}"
        )
    unknown = set(mapped) - target
    missing = target - set(mapped)
    omittable = ARCHIVE_OMITTABLE_TARGET_COLUMNS.get(table, frozenset())
    if unknown or not missing.issubset(omittable):
        raise ArchiveCompatibilityError(
            f"the universe archive COPY columns are not compatible with {table}"
            f" (missing={sorted(missing)}, unknown={sorted(unknown)})"
        )
    return mapped


__all__ = [
    "COPY_HEADER_RE",
    "MIGRATION_DIGEST_COLUMN",
    "MIGRATION_EVIDENCE_TABLE",
    "MIGRATION_LEDGER_TABLE",
    "RESTORE_RESTRICT_RE",
    "RESTORE_SEARCH_PATH",
    "RESTORE_SET_RE",
    "SETVAL_RE",
    "compatible_restore_columns",
    "restore_target_columns",
    "restore_target_sequences",
    "unquote_identifier",
]
