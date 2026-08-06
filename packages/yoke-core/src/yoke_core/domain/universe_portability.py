"""Stable façade for safe portable-universe dump, restore, and validation."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping, Optional

import psycopg

from yoke_core.domain import universe_archive_output
from yoke_core.domain.postgres_client_runtime import (
    postgres_executable as _postgres_executable,
)
from yoke_core.domain.universe_portability_catalog import (
    validate_catalog as _validate_catalog,
    write_restore_list as _write_restore_list,
)
from yoke_core.domain.universe_portability_common import (
    ARCHIVE_FORMAT,
    ARCHIVE_MAGIC,
    CATALOG_BYTES,
    DEFAULT_ARCHIVE_TIMEOUT_S,
    DEFAULT_MAX_ARCHIVE_BYTES,
    DEFAULT_MAX_RESTORE_EXPANSION,
    PUMP_CHUNK_BYTES,
    ArchiveCompatibilityError,
    ArchiveInspection,
    ArchiveInvalidError,
    ArchiveTooLargeError,
    UniversePortabilityError,
    postgres_client_env as _postgres_client_env,
)
from yoke_core.domain.universe_portability_content_contract import (
    ARCHIVE_OMITTABLE_TARGET_TABLES as _ARCHIVE_OMITTABLE_TARGET_TABLES,
    USER_CONTENT_TABLES,
)
from yoke_core.domain.universe_portability_dump import (
    dump_universe as _dump_universe,
)
from yoke_core.domain.universe_portability_inspection import (
    archive_catalog as _archive_catalog,
    archive_catalog_receipt,
    catalog_reader as _bounded_catalog_reader,
    inspect_archive as _inspect_archive_only,
    inspect_archive_with_catalog as _inspect_archive_with_catalog,
)
from yoke_core.domain.universe_portability_restore import (
    restore_universe as _restore_universe,
)
from yoke_core.domain.universe_portability_restore_stream import (
    apply_restore_stream as _apply_restore_stream,
    compatible_restore_columns as _compatible_restore_columns,
)
from yoke_core.domain.universe_portability_validation import (
    all_table_row_counts,
    converge_and_validate_restored_universe,
    user_content_counts,
)


_PUMP_CHUNK_BYTES = PUMP_CHUNK_BYTES
_CATALOG_BYTES = CATALOG_BYTES


def postgres_client_env(
    dsn: str,
    *,
    base: Optional[Mapping[str, str]] = None,
) -> dict[str, str]:
    """Translate a libpq DSN into a credential-safe Postgres client env."""
    return _postgres_client_env(dsn, base=base)


def _catalog_reader(
    stream: object,
    sink: bytearray,
    errors: list[BaseException],
) -> None:
    """Compatibility wrapper retaining the patchable catalog limit."""
    _bounded_catalog_reader(
        stream,
        sink,
        errors,
        max_bytes=_CATALOG_BYTES,
    )


def _inspect_archive(
    path: Path | str,
    *,
    max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    timeout_s: float = DEFAULT_ARCHIVE_TIMEOUT_S,
    pg_restore: Optional[str] = None,
) -> tuple[ArchiveInspection, str]:
    return _inspect_archive_with_catalog(
        path,
        max_bytes=max_bytes,
        timeout_s=timeout_s,
        pg_restore=pg_restore,
        executable_resolver=_postgres_executable,
    )


def inspect_archive(
    path: Path | str,
    *,
    max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    timeout_s: float = DEFAULT_ARCHIVE_TIMEOUT_S,
    pg_restore: Optional[str] = None,
) -> ArchiveInspection:
    """Validate size, bounded catalog, versions, schema, and TOC kinds."""
    return _inspect_archive_only(
        path,
        max_bytes=max_bytes,
        timeout_s=timeout_s,
        pg_restore=pg_restore,
        executable_resolver=_postgres_executable,
    )


def dump_universe(
    dsn: str,
    destination: Path | str,
    *,
    max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    timeout_s: int = DEFAULT_ARCHIVE_TIMEOUT_S,
    pg_dump: Optional[str] = None,
    snapshot: Optional[str] = None,
) -> ArchiveInspection:
    """Create and inspect one portable dump, deleting every failed artifact."""
    return _dump_universe(
        dsn,
        destination,
        max_bytes=max_bytes,
        timeout_s=timeout_s,
        pg_dump=pg_dump,
        snapshot=snapshot,
        executable_resolver=_postgres_executable,
        client_env_builder=postgres_client_env,
        archive_inspector=inspect_archive,
    )


def restore_universe(
    archive: Path | str,
    dsn: str,
    *,
    max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    timeout_s: int = DEFAULT_ARCHIVE_TIMEOUT_S,
    pg_restore: Optional[str] = None,
    finalize: Optional[Callable[[psycopg.Connection], None]] = None,
) -> ArchiveInspection:
    """Restore archive data into a fresh deployed-code schema transactionally."""
    return _restore_universe(
        archive,
        dsn,
        max_bytes=max_bytes,
        timeout_s=timeout_s,
        pg_restore=pg_restore,
        finalize=finalize,
        executable_resolver=_postgres_executable,
    )


__all__ = [
    "ARCHIVE_FORMAT",
    "ARCHIVE_MAGIC",
    "DEFAULT_ARCHIVE_TIMEOUT_S",
    "DEFAULT_MAX_ARCHIVE_BYTES",
    "DEFAULT_MAX_RESTORE_EXPANSION",
    "ArchiveCompatibilityError",
    "ArchiveInspection",
    "ArchiveInvalidError",
    "ArchiveTooLargeError",
    "UniversePortabilityError",
    "USER_CONTENT_TABLES",
    "all_table_row_counts",
    "archive_catalog_receipt",
    "converge_and_validate_restored_universe",
    "dump_universe",
    "inspect_archive",
    "postgres_client_env",
    "restore_universe",
    "user_content_counts",
    "_ARCHIVE_OMITTABLE_TARGET_TABLES",
    "_CATALOG_BYTES",
    "_PUMP_CHUNK_BYTES",
    "_apply_restore_stream",
    "_archive_catalog",
    "_catalog_reader",
    "_compatible_restore_columns",
    "_validate_catalog",
    "_write_restore_list",
    "universe_archive_output",
]
