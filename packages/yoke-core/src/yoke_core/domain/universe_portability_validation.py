"""Post-restore content and exact-schema validation for universes."""

from __future__ import annotations

import logging
import math
from typing import Sequence

from psycopg import conninfo, sql

from yoke_core.domain.universe_portability_common import (
    DEFAULT_ARCHIVE_TIMEOUT_S,
    ArchiveCompatibilityError,
)
from yoke_core.domain.universe_portability_content_contract import (
    USER_CONTENT_COUNT_SQL,
    USER_CONTENT_TABLES,
)


_log = logging.getLogger("yoke.universe.portability")


def user_content_counts(
    conn: object,
    tables: Sequence[str] = USER_CONTENT_TABLES,
) -> dict[str, int]:
    """Return counts for every known user-work table present in this release."""
    present_rows = conn.execute(  # type: ignore[attr-defined]
        "SELECT table_name FROM information_schema.tables"
        " WHERE table_schema = current_schema() AND table_name = ANY(%s)",
        (list(tables),),
    ).fetchall()
    present = {str(row[0]) for row in present_rows}
    counts: dict[str, int] = {}
    for table in tables:
        if table in present:
            count_sql = USER_CONTENT_COUNT_SQL.get(
                table,
                f'SELECT COUNT(*) FROM "{table}"',
            )
            row = conn.execute(count_sql).fetchone()  # type: ignore[attr-defined]
            counts[table] = int(row[0])
        else:
            counts[table] = 0
    return counts


def all_table_row_counts(conn: object) -> dict[str, int]:
    """Raw-count every current-schema base table for fail-closed policy."""
    tables = [
        str(row[0])
        for row in conn.execute(  # type: ignore[attr-defined]
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_schema = current_schema()"
            " AND table_type = 'BASE TABLE' ORDER BY table_name"
        ).fetchall()
    ]
    counts: dict[str, int] = {}
    for table in tables:
        row = conn.execute(  # type: ignore[attr-defined]
            sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                sql.Identifier("public"),
                sql.Identifier(table),
            )
        ).fetchone()
        counts[table] = int(row[0])
    return counts


def converge_and_validate_restored_universe(
    dsn: str,
    *,
    expected_org_slug: str,
    expected_schema_fingerprint: str,
    timeout_s: float = DEFAULT_ARCHIVE_TIMEOUT_S,
) -> dict[str, object]:
    """Converge an imported DB and prove org identity + exact current schema."""
    from yoke_core.domain import db_backend, universe_capability_compatibility
    from yoke_core.domain import qa_requirement_snapshot_convergence as snapshots
    from yoke_core.domain.actor_permissions import seed_roles_and_permissions
    from yoke_core.domain.environment_bootstrap import run_init_chain_at_dsn
    from yoke_core.domain.flow_init import create_or_replace_item_progress_view
    from yoke_core.domain.schema_fingerprint import fingerprint_portable_postgres_schema
    from yoke_contracts.schema_authority import serving_build_authority
    from yoke_core.domain.schema_init import converge_core_schema
    from yoke_core.domain.schema_migrations import _ensure_qa_runs_verdict_trigger
    from yoke_core.domain.schema_readiness import missing_readiness_tables

    parsed_dsn = conninfo.conninfo_to_dict(dsn)
    prior_options = str(parsed_dsn.get("options") or "").strip()
    bounded_options = (
        f"-c statement_timeout={max(1, int(timeout_s * 1000))}"
        f" -c lock_timeout={max(1, int(timeout_s * 1000))}"
        " -c search_path=public,pg_catalog"
    )
    parsed_dsn["options"] = " ".join(
        value for value in (prior_options, bounded_options) if value
    )
    parsed_dsn["connect_timeout"] = str(max(1, min(30, math.ceil(timeout_s))))
    bounded_dsn = conninfo.make_conninfo(**parsed_dsn)
    run_init_chain_at_dsn(
        bounded_dsn,
        emit=lambda line: _log.debug("restored schema converge: %s", line),
    )
    conn = db_backend.connect_psycopg(bounded_dsn)
    try:
        # This validator restored the database at *dsn* for its own use, so it
        # is the only thing serving it; nothing else can be reading the shapes
        # it is about to converge.
        with serving_build_authority():
            converge_core_schema(conn, backup_target_dsn=bounded_dsn)
        seed_roles_and_permissions(conn)
        create_or_replace_item_progress_view(conn)
        _ensure_qa_runs_verdict_trigger(conn)
        snapshots.converge_restored_requirement_snapshots(
            conn, ArchiveCompatibilityError
        )
        conn.commit()
        organizations = conn.execute(
            "SELECT slug FROM organizations ORDER BY id"
        ).fetchall()
        if len(organizations) != 1:
            raise ArchiveCompatibilityError(
                "a portable universe must contain exactly one organization"
            )
        actual_slug = str(organizations[0][0])
        if actual_slug != expected_org_slug:
            raise ArchiveCompatibilityError(
                f"archive organization {actual_slug!r} does not match hosted"
                f" organization {expected_org_slug!r}"
            )
        missing = missing_readiness_tables(conn)
        if missing:
            raise ArchiveCompatibilityError(
                "the restored universe is missing required tables after"
                " convergence: " + ", ".join(missing)
            )
        universe_capability_compatibility.validate_restored_capabilities(conn)
        actual_fingerprint = fingerprint_portable_postgres_schema(conn)
        if actual_fingerprint != expected_schema_fingerprint:
            raise ArchiveCompatibilityError(
                "the restored universe schema is not compatible with the"
                " deployed engine release"
            )
        counts = user_content_counts(conn)
    finally:
        conn.close()
    return {
        "org": expected_org_slug,
        "schema_fingerprint": expected_schema_fingerprint,
        "content_counts": counts,
    }


__all__ = [
    "USER_CONTENT_TABLES",
    "all_table_row_counts",
    "converge_and_validate_restored_universe",
    "user_content_counts",
]
