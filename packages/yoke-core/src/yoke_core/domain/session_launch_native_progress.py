"""Durable native-create progress and duplicate-launch protection."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.session_control.evidence import redacted_evidence_document
from yoke_core.domain.session_launch_store import marker, parse_time, update_launch
from yoke_core.domain.session_launch_types import LaunchRecord


LIVE_NATIVE_PHASES = frozenset({"spawn_started", "spawn_alive"})
REPORTABLE_NATIVE_PHASES = LIVE_NATIVE_PHASES | frozenset(
    {"spawn_completed", "spawn_completed_after_bound", "adapter_complete"}
)


def cleared_native_launch_updates() -> dict[str, None]:
    """Clear telemetry only when a new native attempt is authorized."""
    return {
        "native_launch_pid": None,
        "native_launch_phase": None,
        "native_launch_observed_at": None,
        "spawn_duration_ms": None,
    }


def native_launch_updates(
    evidence: Mapping[str, Any] | None,
    *,
    observed_at: str,
) -> dict[str, object]:
    """Project safe relay evidence onto searchable launch columns."""
    safe = redacted_evidence_document(evidence)
    updates: dict[str, object] = {}
    pid = safe.get("native_launch_pid")
    if isinstance(pid, int) and pid > 0:
        updates["native_launch_pid"] = pid
    phase = safe.get("native_launch_phase")
    if isinstance(phase, str) and phase:
        updates["native_launch_phase"] = phase
    duration = safe.get("duration_ms")
    if isinstance(duration, int) and duration >= 0:
        updates["spawn_duration_ms"] = min(duration, 3_600_000)
    if updates:
        updates["native_launch_observed_at"] = observed_at
    return updates


def _observed_open_native(
    conn: Any,
    launch: LaunchRecord,
    *,
    now: str,
    phases: frozenset[str],
) -> bool:
    if (
        launch.state != "launching"
        or launch.native_launch_pid is None
        or launch.native_launch_pid <= 0
        or launch.native_launch_phase not in phases
        or parse_time(now) >= parse_time(launch.deadline_at)
    ):
        return False
    p = marker(conn)
    row = conn.execute(
        "SELECT 1 FROM session_launch_attempts "
        f"WHERE launch_id={p} AND completed_at IS NULL LIMIT 1",
        (launch.launch_id,),
    ).fetchone()
    return row is not None


def native_spawn_pending(
    conn: Any,
    launch: LaunchRecord,
    *,
    now: str,
) -> bool:
    """Return whether one observed live native still owns this launch window."""
    return _observed_open_native(
        conn, launch, now=now, phases=LIVE_NATIVE_PHASES
    )


def native_attempt_pending(
    conn: Any,
    launch: LaunchRecord,
    *,
    now: str,
) -> bool:
    """Keep one supervised attempt authoritative through its terminal report."""
    return _observed_open_native(
        conn, launch, now=now, phases=REPORTABLE_NATIVE_PHASES
    )


def native_attempt_refusal(launch: LaunchRecord) -> str:
    """Explain why reconciliation or a second create must wait."""
    return (
        f"native attempt for process {launch.native_launch_pid} is still "
        f"in phase {launch.native_launch_phase}; wait for registration through "
        f"{launch.deadline_at}, then reconcile before retry"
    )


def retain_pending_native(
    conn: Any,
    launch: LaunchRecord,
    *,
    now: str,
) -> LaunchRecord | None:
    """Keep retry attached to its observed process instead of creating another."""
    if not native_attempt_pending(conn, launch, now=now):
        return None
    return update_launch(
        conn,
        launch.launch_id,
        state="launching",
        completed_at=None,
        result_code="native_spawn_pending",
    )


__all__ = [
    "LIVE_NATIVE_PHASES",
    "REPORTABLE_NATIVE_PHASES",
    "cleared_native_launch_updates",
    "native_attempt_pending",
    "native_attempt_refusal",
    "native_launch_updates",
    "native_spawn_pending",
    "retain_pending_native",
]
