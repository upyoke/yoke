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


def history_names() -> Tuple[str, ...]:
    """Return the names in Yoke's packaged ordered history."""
    from yoke_core.domain import migrations as history_package
    from yoke_core.domain.migration_history import history_dir, ordered_entries

    return tuple(entry.name for entry in ordered_entries(history_dir(history_package)))


def pending_names(conn: Any, history: Sequence[str]) -> Tuple[str, ...]:
    """Read membership from Yoke's applied-migration ledger."""
    cur = conn.execute("SELECT to_regclass('applied_migrations')")
    if cur.fetchone()[0] is None:
        return tuple(history)
    rows = conn.execute("SELECT migration_name FROM applied_migrations").fetchall()
    applied = {str(row[0]) for row in rows}
    return tuple(name for name in history if name not in applied)


def converge(conn: Any, backup_target_dsn: str) -> None:
    """Run Yoke's complete boot-time schema and history convergence."""
    from yoke_core.domain.schema_init import converge_core_schema

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


def rehearsal_plan() -> RehearsalPlan:
    """Bind the generic rehearsal kernel to Yoke project authority."""
    return RehearsalPlan(
        history=history_names(),
        pending_names=pending_names,
        converge=converge,
        live_ownership_validator=migration_content_ownership_detail,
    )


__all__ = [
    "PLATFORM_DATABASE",
    "TENANT_DATABASE_PATTERN",
    "converge",
    "history_names",
    "migration_content_ownership_detail",
    "pending_names",
    "rehearsal_plan",
    "tenant_databases",
]
