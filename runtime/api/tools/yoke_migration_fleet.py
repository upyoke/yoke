"""Yoke-owned bindings for the generic fleet migration rehearsal kernel.

Tenant naming, the control-plane database, packaged history, ledger columns,
and core-schema convergence are Yoke project facts. Keeping them here lets the
shared rehearsal engine execute any project's declared plan without inheriting
Yoke database names or module paths.
"""

from __future__ import annotations

from typing import Any, Sequence, Tuple

from yoke_core.domain.migration_fleet_preflight import RehearsalPlan
from yoke_core.tools.yoke_migration_fleet import (
    PLATFORM_DATABASE,
    TENANT_DATABASE_PATTERN,
    tenant_databases,
)
from runtime.api.tools.migration_rehearsal_release_surfaces import (
    verify_migrated_release_surfaces,
)


def history_entries() -> Tuple[Any, ...]:
    """Return Yoke's packaged ordered migration entries."""
    from yoke_core.domain import migrations as history_package
    from yoke_core.domain.migration_history import history_dir, ordered_entries

    return tuple(ordered_entries(history_dir(history_package)))


def history_names() -> Tuple[str, ...]:
    """Return the names in Yoke's packaged ordered history."""
    return tuple(entry.name for entry in history_entries())


def pending_names(conn: Any, history: Sequence[str]) -> Tuple[str, ...]:
    """Read membership from Yoke's applied-migration ledger."""
    cur = conn.execute("SELECT to_regclass('applied_migrations')")
    if cur.fetchone()[0] is None:
        return tuple(history)
    rows = conn.execute("SELECT migration_name FROM applied_migrations").fetchall()
    applied = {str(row[0]) for row in rows}
    return tuple(name for name in history if name not in applied)


def converge(conn: Any, backup_target_dsn: str) -> None:
    """Run Yoke's complete boot-time schema and history convergence.

    The preflight converges a throwaway copy it made of each live database,
    never a live one, so it holds the same authority a serving build does over
    what it is changing — even though it is normally run from a workstation
    against a prod-flagged connection, which is precisely the shape the
    convergence guard refuses by default.
    """
    from yoke_contracts.schema_authority import serving_build_authority
    from yoke_core.domain.schema_init import converge_core_schema

    with serving_build_authority():
        converge_core_schema(conn, backup_target_dsn=backup_target_dsn)


def migration_content_ownership_detail(conn: Any) -> str | None:
    """Bind Yoke's declared ledger and evidence objects to live preflight."""
    from yoke_core.domain.migration_content_schema_ownership import (
        migration_content_schema_ownership_detail,
    )
    from yoke_core.domain.migration_yoke_ledger import (
        YOKE_ADOPTION_EVIDENCE_CONTRACT,
        YOKE_LEDGER_CONTRACT,
    )

    return migration_content_schema_ownership_detail(
        conn,
        YOKE_LEDGER_CONTRACT,
        YOKE_ADOPTION_EVIDENCE_CONTRACT,
    )


def load_module(name: str) -> Any:
    """Import one shipped history entry by ledger name."""
    from yoke_core.domain import migrations as history_package
    from yoke_core.domain.migration_history import (
        history_dir,
        load_migration_module,
        ordered_entries,
    )

    entries = {
        entry.name: entry for entry in ordered_entries(history_dir(history_package))
    }
    entry = entries[name]
    return load_migration_module(entry.path, entry.name)


def rehearsal_plan() -> RehearsalPlan:
    """Bind the generic rehearsal kernel to Yoke project authority."""
    return RehearsalPlan(
        history=history_names(),
        pending_names=pending_names,
        converge=converge,
        live_ownership_validator=migration_content_ownership_detail,
        load_module=load_module,
        post_converge_validator=verify_migrated_release_surfaces,
    )


__all__ = [
    "PLATFORM_DATABASE",
    "TENANT_DATABASE_PATTERN",
    "converge",
    "history_entries",
    "history_names",
    "load_module",
    "migration_content_ownership_detail",
    "pending_names",
    "rehearsal_plan",
    "tenant_databases",
]
