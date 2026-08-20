"""Trusted-schema preparation and restore orchestration for universes."""

from __future__ import annotations

import logging
import math
import time
from pathlib import Path
from typing import Callable, Optional

import psycopg
from psycopg import conninfo, sql

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
from yoke_core.domain.universe_portability_restore_transaction import (
    restore_via_libpq,
)


_log = logging.getLogger("yoke.universe.portability")


def reset_restore_target(conn: object) -> None:
    """Drop every current-schema object so one restore path always runs."""
    relations = conn.execute(  # type: ignore[attr-defined]
        "SELECT cls.relname::text, cls.relkind::text"
        " FROM pg_catalog.pg_class cls"
        " JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace"
        " WHERE ns.nspname = current_schema()"
        " AND cls.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')"
        " ORDER BY cls.relname"
    ).fetchall()
    drop_templates = {
        "r": "DROP TABLE IF EXISTS {} CASCADE",
        "p": "DROP TABLE IF EXISTS {} CASCADE",
        "v": "DROP VIEW IF EXISTS {} CASCADE",
        "m": "DROP MATERIALIZED VIEW IF EXISTS {} CASCADE",
        "S": "DROP SEQUENCE IF EXISTS {} CASCADE",
        "f": "DROP FOREIGN TABLE IF EXISTS {} CASCADE",
    }
    for name, kind in relations:
        conn.execute(  # type: ignore[attr-defined]
            sql.SQL(drop_templates[str(kind)]).format(sql.Identifier(str(name)))
        )
    routines = conn.execute(  # type: ignore[attr-defined]
        "SELECT proc.oid::regprocedure::text, proc.prokind::text"
        " FROM pg_catalog.pg_proc proc"
        " JOIN pg_catalog.pg_namespace ns ON ns.oid = proc.pronamespace"
        " WHERE ns.nspname = current_schema()"
        " ORDER BY proc.proname"
    ).fetchall()
    for signature, kind in routines:
        verb = "DROP AGGREGATE" if str(kind) == "a" else "DROP ROUTINE"
        conn.execute(  # type: ignore[attr-defined]
            f"{verb} IF EXISTS {signature} CASCADE"
        )
    conn.commit()  # type: ignore[attr-defined]
    remaining = conn.execute(  # type: ignore[attr-defined]
        "SELECT object_name FROM ("
        " SELECT cls.relname::text AS object_name"
        " FROM pg_catalog.pg_class cls"
        " JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace"
        " WHERE ns.nspname = current_schema()"
        " UNION ALL"
        " SELECT proc.proname::text AS object_name"
        " FROM pg_catalog.pg_proc proc"
        " JOIN pg_catalog.pg_namespace ns ON ns.oid = proc.pronamespace"
        " WHERE ns.nspname = current_schema()"
        ") objects LIMIT 1"
    ).fetchone()
    if remaining is not None:
        raise UniversePortabilityError(
            "the restore destination holds an object the reset does not"
            f" cover: {remaining[0]}"
        )


def prepare_trusted_restore_schema(dsn: str, *, timeout_s: float) -> None:
    """Reset the destination and materialize schema from deployed code."""
    from yoke_contracts.schema_authority import serving_build_authority
    from yoke_core.domain import db_backend
    from yoke_core.domain.environment_bootstrap import run_init_chain_at_dsn

    parsed = conninfo.conninfo_to_dict(dsn)
    prior_options = str(parsed.get("options") or "").strip()
    timeout_ms = max(1, int(timeout_s * 1000))
    bounded_options = (
        f"-c statement_timeout={timeout_ms} -c lock_timeout={timeout_ms}"
        " -c search_path=public,pg_catalog"
    )
    parsed["options"] = " ".join(
        value for value in (prior_options, bounded_options) if value
    )
    parsed["connect_timeout"] = str(max(1, min(30, math.ceil(timeout_s))))
    bounded_dsn = conninfo.make_conninfo(**parsed)
    conn = db_backend.connect_psycopg(bounded_dsn)
    try:
        reset_restore_target(conn)
    finally:
        conn.close()

    # This function just reset the destination: it owns that database
    # outright, and nothing is serving the schema it is about to materialize.
    with serving_build_authority():
        run_init_chain_at_dsn(
            bounded_dsn,
            emit=lambda line: _log.debug("trusted schema init: %s", line),
        )
    conn = db_backend.connect_psycopg(bounded_dsn)
    try:
        from yoke_core.domain.migration_content_restore_guards import (
            truncate_trusted_schema_bootstrap_rows,
        )

        truncate_trusted_schema_bootstrap_rows(conn)
        conn.commit()
    finally:
        conn.close()


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
    prepare_trusted_restore_schema(
        dsn,
        timeout_s=remaining_timeout(deadline, "trusted schema preparation"),
    )
    restore_list = write_restore_list(catalog)
    allowed_tables, allowed_sequences = catalog_data_targets(catalog)
    try:
        restore_via_libpq(
            executable=executable,
            archive=inspection.path,
            restore_list=restore_list,
            dsn=dsn,
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


__all__ = [
    "prepare_trusted_restore_schema",
    "reset_restore_target",
    "restore_universe",
]
