"""Buckets and receipt for the stale-session cleanup sweep."""

from __future__ import annotations

from typing import Any, Dict, List

TERMINATE_ESCALATION = (
    "yoke sessions terminate SESSION-ID --reason R "
    "(releases that session's held work claims)"
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
