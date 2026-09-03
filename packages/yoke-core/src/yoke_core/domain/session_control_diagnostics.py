"""Read-only operator diagnostics for the fleet session roster."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.session_cleanup_holdings import (
    active_holding_sessions,
    effective_cleanup_ttl,
)
from yoke_core.domain.sessions_analytics_core import (
    DEFAULT_STALE_THRESHOLD_MINUTES,
    DEFAULT_STALE_WITH_HOLDINGS_THRESHOLD_MINUTES,
)
from yoke_core.domain.sessions_render_end_chain_pending import (
    chain_pending_state_from_envelope,
)
from yoke_core.domain.sessions_render_end_if_empty import (
    end_session_blocker_facts,
    wake_deliveries_in_flight,
)
from yoke_core.domain.session_keepalive import session_keepalive_holds
from yoke_core.domain.session_launch_pending_delivery import pending_launch_deliveries


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _session_ids(rows: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            str(row.get("session_id") or "") for row in rows if row.get("session_id")
        )
    )


def _latest_messages(
    conn: Any,
    session_ids: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    if not session_ids or not _table_exists(conn, "session_message_recipients"):
        return {}
    marker = _marker(conn)
    ranked = conn.execute(
        "SELECT session_id,message_id,state,created_at,wake_attempt_count FROM ("
        "SELECT session_id,message_id,state,created_at,wake_attempt_count,"
        "ROW_NUMBER() OVER (PARTITION BY session_id "
        "ORDER BY created_at DESC,message_id DESC) AS row_num "
        "FROM session_message_recipients WHERE session_id IN ("
        + ",".join(marker for _ in session_ids)
        + ")) latest WHERE row_num=1",
        session_ids,
    ).fetchall()
    return {
        str(row["session_id"]): {
            "message_id": row["message_id"],
            "state": row["state"],
            "created_at": row["created_at"],
            "wake_attempt_count": int(row["wake_attempt_count"] or 0),
        }
        for row in ranked
    }


def _document_lock_counts(
    conn: Any,
    session_ids: tuple[str, ...],
) -> dict[str, int]:
    if not session_ids or not _table_exists(conn, "strategy_doc_claims"):
        return {}
    marker = _marker(conn)
    rows = conn.execute(
        "SELECT owner_session_id AS session_id,COUNT(*) AS lock_count "
        "FROM strategy_doc_claims WHERE owner_kind='session' "
        "AND released_at IS NULL AND owner_session_id IN ("
        + ",".join(marker for _ in session_ids)
        + ") GROUP BY owner_session_id",
        session_ids,
    ).fetchall()
    return {str(row["session_id"]): int(row["lock_count"] or 0) for row in rows}


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    candidate = f"{text[:-1]}+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _stale_eligible_at(activity_at: Any, ttl_minutes: int) -> str | None:
    parsed = _parse_timestamp(activity_at)
    if parsed is None:
        return None
    eligible = parsed + timedelta(minutes=ttl_minutes)
    return eligible.isoformat().replace("+00:00", "Z")


def session_diagnostics(
    conn: Any,
    rows: list[dict[str, Any]],
    identities: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Project message, end-blocker, and stale-TTL facts for roster rows."""
    session_ids = _session_ids(rows)
    latest_messages = _latest_messages(conn, session_ids)
    document_locks = _document_lock_counts(conn, session_ids)
    holding_sessions = active_holding_sessions(conn)
    wake_deliveries = wake_deliveries_in_flight(conn, session_ids)
    launch_deliveries = pending_launch_deliveries(conn, session_ids)
    keepalive_holds = session_keepalive_holds(conn, session_ids)
    projected: dict[str, dict[str, Any]] = {}
    for row in rows:
        session_id = str(row.get("session_id") or "")
        identity = identities.get(session_id, {})
        ttl_minutes = effective_cleanup_ttl(
            row.get("executor"),
            base_ttl_minutes=DEFAULT_STALE_THRESHOLD_MINUTES,
            executor_ttl_overrides=None,
            has_active_holdings=session_id in holding_sessions,
            holdings_ttl_minutes=DEFAULT_STALE_WITH_HOLDINGS_THRESHOLD_MINUTES,
        )
        terminal = bool(
            identity.get("ended_at")
            or identity.get("terminated_at")
            or row.get("ended_at")
            or row.get("terminated_at")
        )
        blocker = None
        if not terminal:
            blocker = end_session_blocker_facts(
                active_claim_count=len(row.get("claims") or []),
                active_document_lock_count=document_locks.get(session_id, 0),
                keepalive=keepalive_holds.get(session_id),
                launch_delivery=launch_deliveries.get(session_id),
                wake_delivery=wake_deliveries.get(session_id),
                chain_state=chain_pending_state_from_envelope(
                    identity.get("offer_envelope"),
                ),
            )
        projected[session_id] = {
            "latest_message": latest_messages.get(session_id),
            "end_blocker": blocker,
            "effective_stale_ttl_minutes": ttl_minutes,
            "stale_eligible_at": None
            if terminal
            else _stale_eligible_at(row.get("activity_at"), ttl_minutes),
        }
    return projected


__all__ = ["session_diagnostics"]
