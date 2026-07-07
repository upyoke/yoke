"""Schema and constants for Strategize landed-work carry-forward."""

from __future__ import annotations

from typing import Any


#: Default horizon (days) for newly discovered landed work.
DEFAULT_HORIZON_DAYS = 60

#: Default safety-valve cap on the carry candidate set.
DEFAULT_CARRY_LIMIT = 200

VALID_STATES: frozenset[str] = frozenset({"pending", "reflected", "dismissed"})


def ensure_schema(conn: Any) -> None:
    """Create the ``strategize_landed_carry`` table if it does not exist.

    The canonical schema owner is :mod:`yoke_core.domain.schema`, but this
    helper is also exercised by unit tests that build minimal in-memory
    databases, so it must be idempotent and self-sufficient. Callers that
    already run the full schema init can skip this call.
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
