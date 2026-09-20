"""Schema and constants for Strategize landed-work carry-forward."""

from __future__ import annotations

from typing import Any


#: Default horizon (days) for newly discovered landed work.
DEFAULT_HORIZON_DAYS = 60

#: Default safety-valve cap on the carry candidate set.
DEFAULT_CARRY_LIMIT = 200

VALID_STATES: frozenset[str] = frozenset({"pending", "reflected", "dismissed"})


def ensure_schema(conn: Any) -> None:
    """Create the ``strategize_landed_carry`` table for a fixture database.

    **Tests only.** The schema owner is
    :func:`yoke_core.domain.schema_init.converge_core_schema`, which creates this
    table and its index on every boot; serving code reaches an already-converged
    database and must not call this. Executing DDL from a dispatched function
    means a call the registry declares side-effect-free mutates schema, so the
    only sanctioned callers are tests that build a minimal database with no
    converge behind it. Idempotent.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS strategize_landed_carry (
          item_id INTEGER NOT NULL,
          project_id INTEGER NOT NULL REFERENCES projects(id),
          state TEXT NOT NULL DEFAULT 'pending'
            CHECK(state IN ('pending', 'reflected', 'dismissed')),
          first_seen_at TEXT NOT NULL,
          last_updated_at TEXT NOT NULL,
          last_session_id TEXT,
          reason TEXT,
          PRIMARY KEY (project_id, item_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_strategize_landed_carry_state "
        "ON strategize_landed_carry(project_id, state)"
    )
    conn.commit()
