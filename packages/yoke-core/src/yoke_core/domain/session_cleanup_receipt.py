"""Buckets and receipt for the stale-session cleanup sweep."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .session_cleanup_holdings import effective_cleanup_ttl
from .session_staleness import activity_is_stale
from .sessions_analytics_core import DEFAULT_STALE_WITH_HOLDINGS_THRESHOLD_MINUTES

TERMINATE_ESCALATION = (
    "yoke sessions terminate SESSION-ID --reason R "
    "(releases that session's held work claims)"
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
    skipped_between_turns.append({**entry, "reason": "between_turns"})


def reclaim_ttl_for_candidate(
    entry: Dict[str, Any],
    *,
    has_active_holdings: bool,
    stale_threshold_minutes: int,
    executor_ttl_overrides: Optional[Dict[str, int]],
) -> int:
    """Select the TTL used by the mutation recheck."""
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
    elif any(entry["reason"] == "active_work_claim" for entry in skipped_between_turns):
        zero_reason = "active_work_claim"
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
        "escalation": TERMINATE_ESCALATION,
    }
