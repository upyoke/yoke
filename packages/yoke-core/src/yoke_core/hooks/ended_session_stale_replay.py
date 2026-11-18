"""Keep an ended session ended when a hook observed before its end lands late.

A hook client that times out does not cancel its evaluation: the resident
and the authority finish it, sometimes after Stop and SessionEnd have
already ended the row. That late result is not proof of life. The hook's
observation instant comes from its stamped age
(:mod:`yoke_contracts.hook_observation_age`), reconstructed on this
authority's clock, or from an observation batch's recorded instant. A hook
observed at or before the row's ``ended_at`` cannot revive it; a hook with
no instant (an older client) keeps the earlier behaviour and revives.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from yoke_contracts.hook_observation_age import observed_at as payload_observed_at
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import utc_now


def stale_replay(
    conn: Any,
    session_id: str,
    payload_json: Any,
    *,
    observed_at: Optional[datetime] = None,
) -> bool:
    """True when this hook was observed no later than the row's end."""
    origin = observed_at or payload_observed_at(payload_json, utc_now())
    if origin is None or not session_id:
        return False
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT ended_at, terminated_at FROM harness_sessions "
        f"WHERE session_id = {marker}",
        (session_id,),
    ).fetchone()
    if row is None:
        return False
    ended_at, terminated_at = (
        (row["ended_at"], row["terminated_at"]) if hasattr(row, "keys") else row
    )
    if ended_at is None or terminated_at is not None:
        return False
    return parse_instant(origin) <= parse_instant(ended_at)


__all__ = ["stale_replay"]
