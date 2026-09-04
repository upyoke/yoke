"""Per-statement timeout for the server's hook-observation database work.

Hook telemetry is best-effort evidence, but it runs on the same connection
pool that serves every relayed function call. One unbounded query there is
enough to take the pool: on 2026-09-04 an unindexed telemetry lookup held
thirty-one concurrent scans for minutes each and every relayed call behind
them queued. A bounded per-statement timeout makes that failure loud and
local — the batch is refused and retried — instead of silent and fleet-wide.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend


#: Ceiling for a single statement on a hook-observation connection. Every
#: statement on these paths is a keyed probe or a single-row write, so a
#: statement that reaches this is a defect, not a slow but healthy query.
HOOK_OBSERVATION_STATEMENT_TIMEOUT_MS = 5000


def apply_hook_observation_statement_timeout(conn: Any) -> None:
    """Bound every later statement on *conn*; a no-op off Postgres."""
    if not db_backend.connection_is_postgres(conn):
        return
    conn.execute(f"SET statement_timeout = {HOOK_OBSERVATION_STATEMENT_TIMEOUT_MS}")


__all__ = [
    "HOOK_OBSERVATION_STATEMENT_TIMEOUT_MS",
    "apply_hook_observation_statement_timeout",
]
