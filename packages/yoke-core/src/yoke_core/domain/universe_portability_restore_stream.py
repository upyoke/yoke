"""Strict COPY/sequence stream loader for portable universe data."""

from __future__ import annotations

import re
import time

from psycopg import sql

from yoke_core.domain.universe_portability_common import (
    PUMP_CHUNK_BYTES,
    ArchiveCompatibilityError,
    ArchiveInvalidError,
    ArchiveTooLargeError,
    UniversePortabilityError,
)
from yoke_core.domain.universe_portability_content_contract import (
    ARCHIVE_OMITTABLE_TARGET_SEQUENCES,
    ARCHIVE_OMITTABLE_TARGET_TABLES,
)
from yoke_core.domain.universe_portability_restore_contract import (
    COPY_HEADER_RE,
    MIGRATION_DIGEST_COLUMN,
    MIGRATION_EVIDENCE_TABLE,
    MIGRATION_LEDGER_TABLE,
    RESTORE_RESTRICT_RE,
    RESTORE_SEARCH_PATH,
    RESTORE_SET_RE,
    SETVAL_RE,
    compatible_restore_columns,
    restore_target_columns,
    restore_target_sequences,
    unquote_identifier,
)


def consume_restore_bytes(
    consumed: int,
    chunk: bytes,
    *,
    max_sql_bytes: int,
    deadline: float,
) -> int:
    if time.monotonic() >= deadline:
        raise UniversePortabilityError(
            "universe restore exhausted its end-to-end timeout"
        )
    total = consumed + len(chunk)
    if total > max_sql_bytes:
        raise ArchiveTooLargeError(
            "the expanded universe restore exceeds the"
            f" {max_sql_bytes}-byte safety limit"
        )
    return total


def copy_restore_rows(
    source: object,
    copy: object,
    *,
    consumed: int,
    max_sql_bytes: int,
    deadline: float,
) -> int:
    """Stream one textual COPY body without buffering an unbounded row."""
    at_line_start = True
    while True:
        chunk = source.readline(PUMP_CHUNK_BYTES)  # type: ignore[attr-defined]
        if not chunk:
            raise ArchiveInvalidError(
                "the universe archive COPY stream ended before its terminator"
            )
        consumed = consume_restore_bytes(
            consumed,
            chunk,
            max_sql_bytes=max_sql_bytes,
            deadline=deadline,
        )
        if at_line_start and chunk in (b"\\.\n", b"\\.\r\n"):
            return consumed
        copy.write(chunk)  # type: ignore[attr-defined]
        at_line_start = chunk.endswith(b"\n")


def _migration_content_contract_expected(
    target_columns: dict[str, tuple[str, ...]],
) -> bool:
    return (
        MIGRATION_EVIDENCE_TABLE in target_columns
        and MIGRATION_LEDGER_TABLE in target_columns
        and MIGRATION_DIGEST_COLUMN in target_columns[MIGRATION_LEDGER_TABLE]
    )


def _validate_migration_content_archive_shape(
    *, evidence_table_present: bool, ledger_digest_present: bool | None
) -> None:
    if ledger_digest_present is None:
        raise ArchiveCompatibilityError(
            "the universe archive does not describe migration ledger columns"
        )
    if evidence_table_present != ledger_digest_present:
        raise ArchiveCompatibilityError(
            "migration_content_adoptions and applied_migrations.content_sha256 "
            "must be present or absent together"
        )


def apply_restore_stream(
    source: object,
    conn: object,
    *,
    allowed_tables: set[str],
    allowed_sequences: set[str],
    max_sql_bytes: int,
    deadline: float,
) -> None:
    """Apply only catalog-approved COPY data and sequence values via libpq."""
    target_columns = restore_target_columns(conn)
    target_sequences = restore_target_sequences(conn)
    expected_tables = set(target_columns)
    missing_tables = expected_tables - allowed_tables
    extra_tables = allowed_tables - expected_tables
    if not missing_tables.issubset(ARCHIVE_OMITTABLE_TARGET_TABLES) or extra_tables:
        raise ArchiveCompatibilityError(
            "the universe archive TABLE DATA catalog does not match the"
            " deployed schema"
            f" (missing={sorted(missing_tables)}, extra={sorted(extra_tables)})"
        )
    missing_sequences = target_sequences - allowed_sequences
    extra_sequences = allowed_sequences - target_sequences
    if (
        not missing_sequences.issubset(ARCHIVE_OMITTABLE_TARGET_SEQUENCES)
        or extra_sequences
    ):
        raise ArchiveCompatibilityError(
            "the universe archive SEQUENCE SET catalog does not match the"
            " deployed schema"
            f" (missing={sorted(missing_sequences)},"
            f" extra={sorted(extra_sequences)})"
        )
    observed_tables: set[str] = set()
    observed_sequences: set[str] = set()
    ledger_digest_present: bool | None = None
    consumed = 0
    while True:
        raw = source.readline(64 * 1024)  # type: ignore[attr-defined]
        if not raw:
            break
        consumed = consume_restore_bytes(
            consumed, raw, max_sql_bytes=max_sql_bytes, deadline=deadline
        )
        if not raw.endswith(b"\n"):
            raise ArchiveInvalidError(
                "the universe archive contains an oversized restore control line"
            )
        try:
            line = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ArchiveInvalidError(
                "the universe archive restore metadata is not valid UTF-8"
            ) from exc
        if line in ("\n", "\r\n") or line.startswith("--"):
            continue
        if RESTORE_SET_RE.fullmatch(line) is not None:
            continue
        if line.rstrip("\r\n") == RESTORE_SEARCH_PATH:
            continue
        if RESTORE_RESTRICT_RE.fullmatch(line) is not None:
            continue
        copy_match = COPY_HEADER_RE.fullmatch(line)
        if copy_match is not None:
            table_name, columns = _restore_copy_header(
                copy_match, target_columns, allowed_tables, observed_tables
            )
            if table_name == MIGRATION_LEDGER_TABLE:
                ledger_digest_present = MIGRATION_DIGEST_COLUMN in columns
            statement = sql.SQL("COPY {}.{} ({}) FROM STDIN").format(
                sql.Identifier("public"),
                sql.Identifier(table_name),
                sql.SQL(", ").join(sql.Identifier(column) for column in columns),
            )
            with conn.cursor().copy(statement) as copy:  # type: ignore[attr-defined]
                consumed = copy_restore_rows(
                    source,
                    copy,
                    consumed=consumed,
                    max_sql_bytes=max_sql_bytes,
                    deadline=deadline,
                )
            observed_tables.add(table_name)
            continue
        setval_match = SETVAL_RE.fullmatch(line)
        if setval_match is not None:
            sequence_name, raw_value, raw_called = setval_match.groups()
            if (
                sequence_name not in allowed_sequences
                or sequence_name not in target_sequences
            ):
                raise ArchiveInvalidError(
                    "the universe archive sequence target is not enabled"
                )
            if sequence_name in observed_sequences:
                raise ArchiveInvalidError(
                    f"the universe archive repeats SEQUENCE SET for {sequence_name}"
                )
            conn.execute(  # type: ignore[attr-defined]
                "SELECT pg_catalog.setval(%s::regclass, %s, %s)",
                (f"public.{sequence_name}", int(raw_value), raw_called == "true"),
            )
            observed_sequences.add(sequence_name)
            continue
        raise ArchiveInvalidError(
            "the universe archive generated executable restore syntax outside"
            " the COPY/sequence data boundary"
        )
    _validate_observed_catalog(
        observed_tables, observed_sequences, allowed_tables, allowed_sequences
    )
    if _migration_content_contract_expected(target_columns):
        _validate_migration_content_archive_shape(
            evidence_table_present=MIGRATION_EVIDENCE_TABLE in allowed_tables,
            ledger_digest_present=ledger_digest_present,
        )


def _restore_copy_header(
    match: re.Match[str],
    target_columns: dict[str, tuple[str, ...]],
    allowed_tables: set[str],
    observed_tables: set[str],
) -> tuple[str, tuple[str, ...]]:
    schema_name = unquote_identifier(match.group("schema"))
    table_name = unquote_identifier(match.group("table"))
    archive_columns = tuple(
        unquote_identifier(value) for value in match.group("columns").split(", ")
    )
    if schema_name != "public" or table_name not in allowed_tables:
        raise ArchiveInvalidError(
            "the universe archive COPY target is not enabled by its catalog"
        )
    if table_name in observed_tables:
        raise ArchiveInvalidError(
            f"the universe archive repeats TABLE DATA for {table_name}"
        )
    known_columns = target_columns.get(table_name)
    if known_columns is None:
        raise ArchiveInvalidError(
            f"the universe archive COPY columns are invalid for {table_name}"
        )
    return table_name, compatible_restore_columns(
        table_name, archive_columns, known_columns
    )


def _validate_observed_catalog(
    observed_tables: set[str],
    observed_sequences: set[str],
    allowed_tables: set[str],
    allowed_sequences: set[str],
) -> None:
    if observed_tables != allowed_tables:
        raise ArchiveInvalidError(
            "the universe archive TABLE DATA stream does not match its catalog"
            f" (missing={sorted(allowed_tables - observed_tables)},"
            f" extra={sorted(observed_tables - allowed_tables)})"
        )
    if observed_sequences != allowed_sequences:
        raise ArchiveInvalidError(
            "the universe archive SEQUENCE SET stream does not match its catalog"
            f" (missing={sorted(allowed_sequences - observed_sequences)},"
            f" extra={sorted(observed_sequences - allowed_sequences)})"
        )


__all__ = [
    "COPY_HEADER_RE",
    "MIGRATION_DIGEST_COLUMN",
    "MIGRATION_EVIDENCE_TABLE",
    "MIGRATION_LEDGER_TABLE",
    "RESTORE_RESTRICT_RE",
    "RESTORE_SEARCH_PATH",
    "RESTORE_SET_RE",
    "SETVAL_RE",
    "apply_restore_stream",
    "compatible_restore_columns",
    "consume_restore_bytes",
    "copy_restore_rows",
    "restore_target_columns",
    "restore_target_sequences",
    "unquote_identifier",
]
