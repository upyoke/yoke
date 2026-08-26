"""Scheduler work-claim state evaluation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import db_backend
from .session_reclaim_activity_bulk import latest_activity_by_session
from .session_staleness import activity_is_stale
from .scheduler_types import ClaimState
from .sessions_analytics_core import DEFAULT_STALE_THRESHOLD_MINUTES
from .yok_n_parser import parse_item_id_or_none
from .work_claim_targets import scope_int_sql


def _evaluate_claim_states(
    conn: Any,
    item_ids: List[int],
    session_id: Optional[str] = None,
    stale_threshold_minutes: int = DEFAULT_STALE_THRESHOLD_MINUTES,
) -> Dict[int, ClaimState]:
    """Evaluate claim state for a list of internal item ids.

    Returns a dict mapping internal ``items.id`` -> ClaimState.
    """
    if not item_ids:
        return {}

    result: Dict[int, ClaimState] = {iid: ClaimState.UNCLAIMED for iid in item_ids}

    claim_rows = None
    try:
        # Prefer the richer join when the full session schema is available.
        # Restrict to item-target claims; epic_task and process targets are
        # not surfaced as item-level scheduler blockers. Liveness comes
        # from :func:`latest_activity_by_session` post-fetch (last_tool_call_at +
        # heartbeats) so the SQL no longer reads heartbeat columns directly.
        item_scope = scope_int_sql(conn, "wc.scope", "item_id")
        claim_rows = conn.execute(
            f"""SELECT {item_scope} AS item_id, wc.session_id,
                      ases.ended_at AS session_ended_at,
                      ases.executor AS executor,
                      wc.claimed_at AS claimed_at
               FROM work_claims wc
               LEFT JOIN harness_sessions ases ON ases.session_id = wc.session_id
               WHERE wc.released_at IS NULL
                 AND wc.target_kind='item'"""
        ).fetchall()
    except db_backend.operational_error_types(conn):
        if db_backend.connection_is_postgres(conn):
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            # Some test and transitional schemas have a partial work_claims
            # table; still treat non-self live item claims as blocking.
            item_scope = scope_int_sql(conn, "scope", "item_id")
            claim_rows = conn.execute(
                f"""SELECT {item_scope} AS item_id, session_id
                   FROM work_claims
                   WHERE released_at IS NULL
                     AND target_kind='item'"""
            ).fetchall()
        except db_backend.operational_error_types(conn):
            if db_backend.connection_is_postgres(conn):
                try:
                    conn.rollback()
                except Exception:
                    pass
            return result  # Tables may not exist

    # Liveness for every claim-holding session resolves in one pass; asking
    # per row turns a 15-claim board into 30 statements.
    activity_by_session = latest_activity_by_session(
        conn,
        (row[1] for row in claim_rows if len(row) > 2 and row[1]),
    )

    for row in claim_rows:
        raw_item_id = row[0]
        if raw_item_id is None:
            continue
        # Production storage is the bare internal integer; legacy fixture
        # rows may still hold ``YOK-N`` TEXT, which resolves through the
        # canonical parser (prefix + project_sequence). The bare internal
        # id matches the scheduler's caller-provided item keys.
        resolved_item = parse_item_id_or_none(raw_item_id, conn=conn)
        if resolved_item is None:
            continue
        item_id = int(resolved_item)
        claim_session = row[1]
        if item_id not in result:
            continue

        session_ended = row[2] if len(row) > 2 else None
        executor = row[3] if len(row) > 3 else None
        claimed_at = row[4] if len(row) > 4 else None
        activity_at: Optional[str] = None
        if len(row) > 2 and claim_session:
            activity_at = activity_by_session.get(str(claim_session))
        if activity_at is None:
            activity_at = claimed_at
        session_is_stale = (
            activity_is_stale(
                activity_at,
                executor=executor,
                base_ttl_minutes=stale_threshold_minutes,
            )
            if len(row) > 2
            else False
        )

        if session_id and claim_session == session_id:
            result[item_id] = ClaimState.CLAIMED_BY_SELF
        elif session_ended is not None or session_is_stale:
            result[item_id] = ClaimState.CLAIMED_BY_STALE
        else:
            result[item_id] = ClaimState.CLAIMED_BY_OTHER_LIVE

    return result
