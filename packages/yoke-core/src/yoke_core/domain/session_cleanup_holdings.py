"""Active holdings and TTL selection for stale-session cleanup."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from .schema_common import _table_exists
from .sessions_render_reclaim import _resolve_effective_ttl


def _add_session_ids(target: set[str], rows: list[Any], column: str) -> None:
    for row in rows:
        value = row[column]
        if value:
            target.add(str(value))


def active_holding_sessions(conn: Any) -> set[str]:
    """Return sessions holding active work or document claims.

    Shared-operation holds are work_claims rows, so the first query
    already covers them.
    """
    sessions: set[str] = set()
    if _table_exists(conn, "work_claims"):
        _add_session_ids(
            sessions,
            conn.execute(
                "SELECT DISTINCT session_id FROM work_claims WHERE released_at IS NULL"
            ).fetchall(),
            "session_id",
        )
    if _table_exists(conn, "strategy_doc_claims"):
        _add_session_ids(
            sessions,
            conn.execute(
                "SELECT DISTINCT owner_session_id FROM strategy_doc_claims "
                "WHERE owner_kind = 'session' AND released_at IS NULL"
            ).fetchall(),
            "owner_session_id",
        )
    return sessions


def effective_cleanup_ttl(
    executor: Optional[str],
    *,
    base_ttl_minutes: int,
    executor_ttl_overrides: Optional[Mapping[str, int]],
    has_active_holdings: bool,
    holdings_ttl_minutes: int,
) -> int:
    """Select the empty-session or holdings-aware stale threshold."""
    short_ttl = _resolve_effective_ttl(
        executor,
        base_ttl_minutes,
        dict(executor_ttl_overrides) if executor_ttl_overrides is not None else None,
    )
    if not has_active_holdings:
        return short_ttl
    return max(short_ttl, int(holdings_ttl_minutes))


__all__ = ["active_holding_sessions", "effective_cleanup_ttl"]
