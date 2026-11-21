"""Trusted-schema preparation and restore orchestration for universes."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional

import psycopg
from psycopg import conninfo

from yoke_core.domain.postgres_client_runtime import postgres_executable
from yoke_core.domain.universe_portability_catalog import (
    catalog_data_targets,
    write_restore_list,
)
from yoke_core.domain.universe_portability_common import (
    DEFAULT_ARCHIVE_TIMEOUT_S,
    DEFAULT_MAX_ARCHIVE_BYTES,
    DEFAULT_MAX_RESTORE_EXPANSION,
    ArchiveInspection,
    UniversePortabilityError,
    remaining_timeout,
)
from yoke_core.domain.universe_portability_inspection import (
    inspect_archive_with_catalog,
)
from yoke_core.domain.universe_portability_restore_schema import (
    IMPORT_SCHEMA,
    staged_restore_schema,
)
from yoke_core.domain.universe_portability_restore_transaction import (
    restore_via_libpq,
)


def restore_universe(
    archive: Path | str,
    dsn: str,
    *,
    max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    timeout_s: int = DEFAULT_ARCHIVE_TIMEOUT_S,
    pg_restore: Optional[str] = None,
    finalize: Optional[Callable[[psycopg.Connection], None]] = None,
    executable_resolver: Callable[[str], str] = postgres_executable,
) -> ArchiveInspection:
    """Restore archive data into a fresh deployed-code schema transactionally."""
    deadline = time.monotonic() + timeout_s
    inspection, catalog = inspect_archive_with_catalog(
        archive,
        max_bytes=max_bytes,
        timeout_s=remaining_timeout(deadline, "restore"),
        pg_restore=pg_restore,
        executable_resolver=executable_resolver,
    )
    executable = pg_restore or executable_resolver("pg_restore")
    dbname = conninfo.conninfo_to_dict(dsn).get("dbname")
    if not dbname:
        raise UniversePortabilityError("the restore target DSN must name a database")
    restore_list = write_restore_list(catalog)
    allowed_tables, allowed_sequences = catalog_data_targets(catalog)
    try:
        with staged_restore_schema(dsn, deadline):
            restore_via_libpq(
                executable=executable,
                archive=inspection.path,
                restore_list=restore_list,
                dsn=dsn,
                target_schema=IMPORT_SCHEMA,
                allowed_tables=allowed_tables,
                allowed_sequences=allowed_sequences,
                timeout_s=remaining_timeout(deadline, "restore"),
                max_sql_bytes=max(
                    64 * 1024 * 1024,
                    max_bytes * DEFAULT_MAX_RESTORE_EXPANSION,
                ),
                finalize=finalize,
            )
    finally:
        restore_list.unlink(missing_ok=True)
    return inspection


__all__ = ["restore_universe"]
