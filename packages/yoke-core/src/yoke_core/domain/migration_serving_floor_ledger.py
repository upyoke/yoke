"""Repair and verify serving floors recorded in a migration ledger."""

from __future__ import annotations

from typing import Any, Sequence, Tuple

from yoke_core.domain import db_backend, migration_serving_version
from yoke_core.domain.migration_history import MigrationEntry
from yoke_core.domain.migration_ledger_contract import LedgerContract


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def backfill_serving_floors(
    conn: Any,
    history: Sequence[MigrationEntry],
    *,
    ledger: LedgerContract,
) -> Tuple[str, ...]:
    """Fill missing ledger floors from permanent applied history entries.

    Only literal declarations can be backfilled. The next-release sentinel
    names the release that carried the entry when it was applied, and this
    runs long afterwards with no way to learn which one that was; writing a
    version it cannot know would be worse evidence than the absence it repairs.
    """
    selected = ledger
    rows = conn.execute(
        f"SELECT {selected.entry_column} FROM {selected.table}"
    ).fetchall()
    recorded = {str(row[0]) for row in rows}
    repaired: list[str] = []
    marker = _placeholder(conn)
    for entry in history:
        if entry.name not in recorded:
            continue
        minimum = migration_serving_version.entry_minimum(entry)
        if minimum == migration_serving_version.NEXT_RELEASE:
            minimum = None
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
    ledger: LedgerContract,
) -> Tuple[str, ...]:
    """Applied entries whose declared rollback floor is absent in the ledger.

    A sentinel declaration is not among them: it resolves per artifact, so an
    absent row value records that the applying build had no release identity
    rather than that evidence was lost.
    """
    selected = ledger
    rows = conn.execute(
        f"SELECT {selected.entry_column} FROM {selected.table} "
        f"WHERE {selected.serving_floor_column} IS NULL"
    ).fetchall()
    missing = {str(row[0]) for row in rows}
    findings = []
    for entry in history:
        if entry.name not in missing:
            continue
        if migration_serving_version.entry_minimum(entry) not in {
            None,
            migration_serving_version.NEXT_RELEASE,
        }:
            findings.append(entry.name)
    return tuple(findings)


__all__ = ["backfill_serving_floors", "missing_declared_serving_floors"]
