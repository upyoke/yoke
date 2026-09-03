"""Additive schema for the machine registry.

One row per Yoke machine — a host that runs a relay and harness surfaces. The
row is the single identity every other machine-keyed surface points at:
``session_relays.machine_id``, ``harness_sessions.machine_id``, launch rows,
plan-limit readings, and surface-policy marks all name the same registered id.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_init_apply import execute_schema_script


MACHINES_SQL = """
CREATE TABLE IF NOT EXISTS machines (
    machine_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner_actor_id INTEGER NOT NULL REFERENCES actors(id),
    proof_public_key TEXT NOT NULL,
    access TEXT NOT NULL DEFAULT '{}',
    registered_at TEXT NOT NULL,
    last_seen_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_machines_owner
    ON machines(owner_actor_id, name);
"""


def ensure_machine_registry_schema(conn: Any, *, commit: bool = True) -> None:
    """Converge the machines table, committing unless the caller owns the txn."""
    execute_schema_script(conn, MACHINES_SQL)
    if commit:
        conn.commit()


__all__ = ["MACHINES_SQL", "ensure_machine_registry_schema"]
