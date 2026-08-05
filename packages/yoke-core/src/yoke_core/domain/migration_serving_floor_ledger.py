"""Repair and verify serving floors recorded in a migration ledger."""

from __future__ import annotations

from typing import Any, Sequence, Tuple

from yoke_core.domain import db_backend, migration_serving_version
from yoke_core.domain.migration_history import MigrationEntry, load_migration_module

LEDGER_TABLE = "applied_migrations"


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def backfill_serving_floors(
    conn: Any, history: Sequence[MigrationEntry],
) -> Tuple[str, ...]:
    """Fill missing ledger floors from permanent applied history entries."""
    rows = conn.execute(f"SELECT migration_name FROM {LEDGER_TABLE}").fetchall()
    recorded = {str(row[0]) for row in rows}
    repaired: list[str] = []
    marker = _placeholder(conn)
    for entry in history:
        if entry.name not in recorded:
            continue
        module = load_migration_module(entry.path, entry.name)
        minimum = migration_serving_version.declared_minimum(module)
        if minimum is None:
            continue
        cursor = conn.execute(
            f"UPDATE {LEDGER_TABLE} SET minimum_serving_version = {marker} "
            f"WHERE migration_name = {marker} AND minimum_serving_version IS NULL",
            (minimum, entry.name),
        )
        if getattr(cursor, "rowcount", 0):
            repaired.append(entry.name)
    return tuple(repaired)


def missing_declared_serving_floors(
    conn: Any, history: Sequence[MigrationEntry],
) -> Tuple[str, ...]:
    """Applied entries whose declared rollback floor is absent in the ledger."""
    rows = conn.execute(
        f"SELECT migration_name FROM {LEDGER_TABLE} "
        "WHERE minimum_serving_version IS NULL"
    ).fetchall()
    missing = {str(row[0]) for row in rows}
    findings = []
    for entry in history:
        if entry.name not in missing:
            continue
        module = load_migration_module(entry.path, entry.name)
        if migration_serving_version.declared_minimum(module) is not None:
            findings.append(entry.name)
    return tuple(findings)


__all__ = ["backfill_serving_floors", "missing_declared_serving_floors"]
