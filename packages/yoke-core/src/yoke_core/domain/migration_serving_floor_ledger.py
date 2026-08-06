"""Repair and verify serving floors recorded in a migration ledger."""

from __future__ import annotations

from typing import Any, Sequence, Tuple

from yoke_core.domain import db_backend, migration_serving_version
from yoke_core.domain.migration_history import MigrationEntry, load_migration_module
from yoke_core.domain.migration_ledger_contract import LedgerContract


def _permanent_history_compatibility_ledger() -> LedgerContract:
    """Bind immutable Yoke entry 0004's historical two-argument call."""
    from yoke_core.domain.migration_yoke_ledger import YOKE_LEDGER_CONTRACT

    return YOKE_LEDGER_CONTRACT


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def backfill_serving_floors(
    conn: Any,
    history: Sequence[MigrationEntry],
    *,
    ledger: LedgerContract | None = None,
) -> Tuple[str, ...]:
    """Fill missing ledger floors from permanent applied history entries."""
    selected = ledger or _permanent_history_compatibility_ledger()
    rows = conn.execute(
        f"SELECT {selected.entry_column} FROM {selected.table}"
    ).fetchall()
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
            f"UPDATE {selected.table} SET {selected.serving_floor_column} = {marker} "
            f"WHERE {selected.entry_column} = {marker} "
            f"AND {selected.serving_floor_column} IS NULL",
            (minimum, entry.name),
        )
        if getattr(cursor, "rowcount", 0):
            repaired.append(entry.name)
    return tuple(repaired)


def missing_declared_serving_floors(
    conn: Any,
    history: Sequence[MigrationEntry],
    *,
    ledger: LedgerContract | None = None,
) -> Tuple[str, ...]:
    """Applied entries whose declared rollback floor is absent in the ledger."""
    selected = ledger or _permanent_history_compatibility_ledger()
    rows = conn.execute(
        f"SELECT {selected.entry_column} FROM {selected.table} "
        f"WHERE {selected.serving_floor_column} IS NULL"
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
