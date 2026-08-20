"""Declared project-ledger reads and writes for boot migration appliers."""

from __future__ import annotations

import hashlib
from typing import Any, Optional, Sequence, Set, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.migration_audit_receipts import now_stamp
from yoke_core.domain.migration_history import MigrationEntry
from yoke_core.domain.migration_ledger_contract import LedgerContract

#: Advisory-lock id serializing migration apply on one database. Postgres
#: advisory locks already carry the database in their lock tag, so a single
#: constant gives per-database exclusion for free.
MIGRATION_APPLY_LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"yoke.migration.boot_apply").digest()[:8],
    "big",
    signed=True,
)


def applied_names(conn: Any, ledger: LedgerContract) -> Set[str]:
    """Return migration names recorded in the declared membership ledger."""
    rows = conn.execute(f"SELECT {ledger.entry_column} FROM {ledger.table}").fetchall()
    return {str(row[0]) for row in rows}


def pending_entries(
    conn: Any,
    history: Sequence[MigrationEntry],
    ledger: LedgerContract,
) -> Tuple[MigrationEntry, ...]:
    """Return history entries absent from the declared ledger, in order."""
    recorded = applied_names(conn, ledger)
    return tuple(entry for entry in history if entry.name not in recorded)


def record_applied(
    conn: Any,
    entry: MigrationEntry,
    *,
    ledger: LedgerContract,
    applied_by: str,
    content_sha256: str,
    minimum_serving_version: Optional[str] = None,
) -> None:
    """Insert membership, floor, and raw-byte digest in one transaction."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    conn.execute(
        f"INSERT INTO {ledger.table} "
        f"({ledger.entry_column}, {ledger.applied_at_column}, "
        f"{ledger.applied_by_column}, {ledger.serving_floor_column}, "
        f"{ledger.digest_column}) "
        f"VALUES ({marker}, {marker}, {marker}, {marker}, {marker}) "
        f"ON CONFLICT ({ledger.entry_column}) DO NOTHING",
        (
            entry.name,
            now_stamp(),
            applied_by,
            minimum_serving_version,
            content_sha256,
        ),
    )


def acquire_apply_lock(conn: Any) -> None:
    if not db_backend.connection_is_postgres(conn):
        return
    conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_APPLY_LOCK_KEY,))


def release_apply_lock(conn: Any) -> None:
    if not db_backend.connection_is_postgres(conn):
        return
    try:
        conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_APPLY_LOCK_KEY,))
    except Exception:  # noqa: BLE001 — the session ending releases it anyway
        pass


__all__ = [
    "MIGRATION_APPLY_LOCK_KEY",
    "acquire_apply_lock",
    "applied_names",
    "pending_entries",
    "record_applied",
    "release_apply_lock",
]
