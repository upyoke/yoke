"""Shared SQLite fixtures for the boot migration tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from yoke_core.domain.migration_audit_receipts import now_stamp, record_missing_receipts
from yoke_core.domain.migration_audit_schema import ensure_migration_audit_table
from yoke_core.domain.migration_boot_apply import (
    apply_pending as _apply_pending,
    stamp_history as _stamp_history,
)
from yoke_core.domain.migration_boot_ledger import (
    applied_names as _applied_names,
    pending_entries as _pending_entries,
)
from yoke_core.domain.migration_history import ordered_entries
from yoke_core.domain.migration_yoke_ledger import (
    YOKE_LEDGER_CONTRACT,
    ensure_yoke_migration_ledger,
)

RESTORE_POINT = "snapshot:test-restore-point"


def applied_names(conn):
    return _applied_names(conn, YOKE_LEDGER_CONTRACT)


def pending_entries(conn, history):
    return _pending_entries(conn, history, YOKE_LEDGER_CONTRACT)


def apply_pending(conn, **kwargs):
    kwargs.setdefault(
        "attribution",
        {
            "session_id": "test-session",
            "actor_id": "test-actor",
            "source_branch": "main",
            "source_commit": "test-commit",
        },
    )
    kwargs.setdefault("model_name", "primary")
    return _apply_pending(conn, ledger=YOKE_LEDGER_CONTRACT, **kwargs)


def stamp_history(conn, history, **kwargs):
    return _stamp_history(conn, history, ledger=YOKE_LEDGER_CONTRACT, **kwargs)


def connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    ensure_yoke_migration_ledger(conn)
    ensure_migration_audit_table(conn)
    conn.execute("CREATE TABLE marks (name TEXT)")
    conn.commit()
    return conn


def history(tmp_path: Path, *names: str, failing: str | None = None):
    """Build a history whose entries each record that they ran."""
    for name in names:
        body = (
            "def apply(conn):\n"
            f"    conn.execute(\"INSERT INTO marks VALUES ('{name}')\")\n"
        )
        if name == failing:
            body += "    raise RuntimeError('entry failed')\n"
        (tmp_path / f"{name}.py").write_text(body)
    return ordered_entries(tmp_path)


def heal(conn: sqlite3.Connection, migration_history) -> tuple[str, ...]:
    return record_missing_receipts(
        conn,
        migration_history,
        applied=applied_names(conn),
        stamp=now_stamp(),
        restore_point=RESTORE_POINT,
        attribution={
            "session_id": "test-session",
            "actor_id": "test-actor",
            "source_branch": "main",
            "source_commit": "test-commit",
        },
        model_name="primary",
    )


def marks(conn: sqlite3.Connection) -> list[str]:
    return [row[0] for row in conn.execute("SELECT name FROM marks").fetchall()]


__all__ = [
    "RESTORE_POINT",
    "applied_names",
    "apply_pending",
    "connection",
    "heal",
    "history",
    "marks",
    "pending_entries",
    "stamp_history",
]
