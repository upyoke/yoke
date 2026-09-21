"""Probe-aligned reclaim of ``claimed_by_stale`` item holders.

The fleet probe classifies an item ``claimed_by_stale`` with the short
session TTL, not the holdings TTL. The sweep still uses the holdings TTL
as the default for a session that may be between turns. When the probe has
already classified a holder, the sweep frees that same holder without
waiting out the holdings bound. Parked release-wait owners stay spared:
the probe does not classify them stale, and ``release_wait_sweep`` still
guards the mutation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import db_backend
from .scheduler_claims import _evaluate_claim_states
from .scheduler_types import ClaimState
from .schema_common import _table_exists
from .session_cleanup_holdings import effective_cleanup_ttl
from .session_staleness import activity_is_stale
from .sessions_analytics_core import (
    DEFAULT_STALE_WITH_HOLDINGS_THRESHOLD_MINUTES,
)
from .work_claim_target_sql import scope_int_sql

REASON_CLAIMED_BY_STALE = "claimed_by_stale"
TERMINATE_ESCALATION = (
    "yoke sessions terminate SESSION-ID --reason R "
    "(releases that session's held work claims)"
)


def _item_ids_held(conn: Any, session_id: str) -> List[int]:
    if not _table_exists(conn, "work_claims"):
        return []
    item_scope = scope_int_sql(conn, "scope", "item_id")
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        f"SELECT {item_scope} AS item_id FROM work_claims "
        f"WHERE session_id={marker} AND released_at IS NULL "
        "AND target_kind='item'",
        (session_id,),
    ).fetchall()
    item_ids: List[int] = []
    for row in rows:
        raw = row["item_id"] if hasattr(row, "keys") else row[0]
        if raw is None:
            continue
        item_ids.append(int(raw))
    return item_ids


def probe_classifies_item_holder_stale(conn: Any, session_id: str) -> bool:
    """True when the fleet probe would report this holder ``claimed_by_stale``."""
    item_ids = _item_ids_held(conn, session_id)
    if not item_ids:
        return False
    states = _evaluate_claim_states(conn, item_ids)
    return any(
        states.get(item_id) == ClaimState.CLAIMED_BY_STALE for item_id in item_ids
    )


def bucket_holdings_spared_session(
    conn: Any,
    sid: str,
    entry: Dict[str, Any],
    progress_stale_flag: bool,
    activity_at: Optional[str],
    stale_threshold_minutes: int,
    progress_stale: List[Dict[str, Any]],
    heartbeat_stale: List[Dict[str, Any]],
    skipped_between_turns: List[Dict[str, Any]],
) -> None:
    """Place a holdings-TTL-fresh session into the matching sweep bucket."""
    if progress_stale_flag:
        progress_stale.append({**entry, "reason": "progress_stale"})
        return
    if not activity_is_stale(
        activity_at,
        executor=None,
        base_ttl_minutes=stale_threshold_minutes,
        executor_ttl_overrides={},
    ):
        return
    if probe_classifies_item_holder_stale(conn, sid):
        heartbeat_stale.append(
            {
                **entry,
                "reason": REASON_CLAIMED_BY_STALE,
                "effective_ttl_minutes": stale_threshold_minutes,
            }
        )
        return
    skipped_between_turns.append({**entry, "reason": "between_turns"})


def reclaim_ttl_for_candidate(
    entry: Dict[str, Any],
    *,
    has_active_holdings: bool,
    stale_threshold_minutes: int,
    executor_ttl_overrides: Optional[Dict[str, int]],
) -> int:
    """TTL the mutation recheck uses; probe-stale holders keep the short bound."""
    if entry.get("reason") == REASON_CLAIMED_BY_STALE:
        return stale_threshold_minutes
    return effective_cleanup_ttl(
        entry["executor"],
        base_ttl_minutes=stale_threshold_minutes,
        executor_ttl_overrides=executor_ttl_overrides,
        has_active_holdings=has_active_holdings,
        holdings_ttl_minutes=DEFAULT_STALE_WITH_HOLDINGS_THRESHOLD_MINUTES,
    )


def sweep_receipt(
    *,
    never_engaged: List[Dict[str, Any]],
    heartbeat_stale: List[Dict[str, Any]],
    progress_stale: List[Dict[str, Any]],
    skipped_between_turns: List[Dict[str, Any]],
    total_reclaimed: int,
    scratch_cleanup: Dict[str, Any],
) -> Dict[str, Any]:
    if total_reclaimed:
        zero_reason = None
    elif skipped_between_turns:
        zero_reason = "within_retention_bound"
    else:
        zero_reason = "nothing_stale"
    return {
        "never_engaged": never_engaged,
        "heartbeat_stale": heartbeat_stale,
        "progress_stale": progress_stale,
        "skipped_between_turns": skipped_between_turns,
        "total_reclaimed": total_reclaimed,
        "scratch_cleanup": scratch_cleanup,
        "zero_reclaim_reason": zero_reason,
        "retention_bound_minutes": DEFAULT_STALE_WITH_HOLDINGS_THRESHOLD_MINUTES,
        "escalation": TERMINATE_ESCALATION,
    }


__all__ = [
    "REASON_CLAIMED_BY_STALE",
    "TERMINATE_ESCALATION",
    "bucket_holdings_spared_session",
    "probe_classifies_item_holder_stale",
    "reclaim_ttl_for_candidate",
    "sweep_receipt",
]
