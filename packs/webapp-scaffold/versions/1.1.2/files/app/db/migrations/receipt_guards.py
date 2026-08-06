"""Exact SQLite guards for append-only migration adoption receipts."""

from __future__ import annotations


RECEIPT_TABLE = "migration_adoption_receipts"
RECEIPT_GUARDS = {
    "migration_adoption_receipts_no_update": "UPDATE",
    "migration_adoption_receipts_no_delete": "DELETE",
}


def _guard_sql(name: str, operation: str) -> str:
    return (
        f"CREATE TRIGGER {name} BEFORE {operation} ON {RECEIPT_TABLE} "
        "BEGIN SELECT RAISE(ABORT, "
        "'migration adoption receipts are append-only'); END"
    )


def _normalized_sql(value) -> str:
    return " ".join(str(value or "").split()).rstrip(";").casefold()


def adoption_receipt_guard_state(conn) -> dict:
    """Require each expected name to carry its exact append-only semantics."""
    table_present = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (RECEIPT_TABLE,),
    ).fetchone() is not None
    invalid = []
    if table_present:
        installed = {
            str(name): sql
            for name, sql in conn.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type='trigger' AND tbl_name=?",
                (RECEIPT_TABLE,),
            ).fetchall()
        }
        invalid = sorted(
            name
            for name, operation in RECEIPT_GUARDS.items()
            if _normalized_sql(installed.get(name))
            != _normalized_sql(_guard_sql(name, operation))
        )
    return {
        "adoption_receipt_table_present": table_present,
        "adoption_receipt_guards_ready": not invalid,
        "missing_adoption_receipt_guards": invalid,
    }


def ensure_adoption_receipt_guards(conn) -> None:
    """Create the receipt ledger and replace every guard with exact SQL."""
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {RECEIPT_TABLE} ("
        "receipt_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "manifest_sha256 TEXT NOT NULL UNIQUE, engine_version TEXT NOT NULL, "
        "source_artifact TEXT NOT NULL, source_sha256 TEXT NOT NULL, "
        "source_commit TEXT NOT NULL, adopted_by TEXT NOT NULL, "
        "adopted_entries_json TEXT NOT NULL, "
        "recorded_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    for name, operation in RECEIPT_GUARDS.items():
        conn.execute(f"DROP TRIGGER IF EXISTS {name}")
        conn.execute(_guard_sql(name, operation))


__all__ = [
    "RECEIPT_GUARDS",
    "RECEIPT_TABLE",
    "adoption_receipt_guard_state",
    "ensure_adoption_receipt_guards",
]
