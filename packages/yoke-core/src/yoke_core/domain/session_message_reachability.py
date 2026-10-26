"""What sending a message to a holder does, independent of native liveness."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.session_mode import session_is_parked
from yoke_core.domain.session_native_process_observation import (
    current_native_process_observation,
)
from yoke_core.domain.session_resume_in_flight import resumable_from_transcript

DELIVERY_UNKNOWN = "delivery state unknown — inspect session evidence"


def message_reachability(row: Mapping[str, Any], *, resuming: bool = False) -> str:
    """Describe recorded turn/wait state without inferring a running process.

    A native exit ends a turn even before its posture hook arrives. A declared
    park explains the wait; containment remains visible even with exit code zero.
    Surface capabilities decide whether a message can wake a stopped turn.
    """
    process = current_native_process_observation(row, include_expected_exit=True)
    if resuming and process:
        return "message wake in flight — let the turn start"
    evidence = process.get("evidence", {}) if process else {}
    contained = str(evidence.get("containment_reason") or "").strip()
    prefix = f"contained by sweep: {contained}, claims held; " if contained else ""
    if session_is_parked(row.get("mode")):
        reason = str(row.get("quiet_reason") or "").strip()
        return prefix + (
            f"parked {reason}" if reason else "parked waiting (reason not recorded)"
        )
    if process or row.get("turn_posture") == "waiting":
        if resumable_from_transcript(
            row.get("executor_surface"), row.get("executor_version")
        ):
            return prefix + "between turns — message wakes it"
        return prefix + "between turns — message needs operator input on this surface"
    if row.get("turn_posture") == "running":
        return prefix + "mid-turn — message arrives at its next tool call"
    return prefix + DELIVERY_UNKNOWN
