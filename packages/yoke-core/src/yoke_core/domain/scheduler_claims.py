"""Scheduler work-claim state evaluation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import db_backend
from .session_reclaim_activity import latest_activity
from .session_staleness import activity_is_stale
from .scheduler_types import ClaimState
from .sessions_analytics_core import DEFAULT_STALE_THRESHOLD_MINUTES

def _evaluate_claim_states(
    conn: Any,
    item_ids: List[str],
    session_id: Optional[str] = None,
    stale_threshold_minutes: int = DEFAULT_STALE_THRESHOLD_MINUTES,
) -> Dict[str, ClaimState]:
    """Evaluate claim state for a list of items.

    Returns a dict mapping item_id -> ClaimState.
    """
    if not item_ids:
        return {}

    result: Dict[str, ClaimState] = {iid: ClaimState.UNCLAIMED for iid in item_ids}

    claim_rows = None
    try:
        # Prefer the richer join when the full session schema is available.
        # Restrict to item-target claims; epic_task and process targets are
        # not surfaced as item-level scheduler blockers. Liveness comes
        # from :func:`latest_activity` post-fetch (last_tool_call_at +
        # heartbeats) so the SQL no longer reads heartbeat columns directly.
        claim_rows = conn.execute(
            """SELECT wc.item_id, wc.session_id,
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
            claim_rows = conn.execute(
                """SELECT item_id, session_id
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

    for row in claim_rows:
        raw_item_id = row[0]
        if raw_item_id is None:
            continue
        # Tolerate test fixtures that still store YOK-N as TEXT; production
        # post-cutover storage is bare integer.
        raw_text = str(raw_item_id)
        if raw_text.upper().startswith("YOK-"):
            raw_text = raw_text[4:]
        try:
            item_id = f"YOK-{int(raw_text)}"
        except ValueError:
            continue
        claim_session = row[1]
        if item_id not in result:
            continue

        session_ended = row[2] if len(row) > 2 else None
        executor = row[3] if len(row) > 3 else None
        claimed_at = row[4] if len(row) > 4 else None
        activity_at: Optional[str] = None
        if len(row) > 2 and claim_session:
            activity_at = latest_activity(
                conn, str(claim_session), executor=executor,
            )
        if activity_at is None:
            activity_at = claimed_at
        session_is_stale = (
            activity_is_stale(
                activity_at,
                executor=executor,
                base_ttl_minutes=stale_threshold_minutes,
            )
            if len(row) > 2 else False
        )

        if session_id and claim_session == session_id:
            result[item_id] = ClaimState.CLAIMED_BY_SELF
        elif session_ended is not None or session_is_stale:
            result[item_id] = ClaimState.CLAIMED_BY_STALE
        else:
            result[item_id] = ClaimState.CLAIMED_BY_OTHER_LIVE

    return result
