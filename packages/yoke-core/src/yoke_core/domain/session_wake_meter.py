"""Whether a session's pinned model can survive a wake.

The connected relay already publishes the meter a wake would spend. A path
that reports the wake delivered while that meter is at zero is a success
report for work that can only die. This module is the one computer: an
operator-issued wake, an automatic claim, the session roster, and the
steering report all read it so they cannot disagree.

Exhaustion is the existing pool reading
(:func:`yoke_contracts.session_control.model_billing_pools.pool_exhaustion`):
affirmative, readable, pool-matched zero. Unknown is never exhaustion, and
this never raises or bypasses a plan limit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from yoke_contracts.session_control.model_billing_pools import pool_exhaustion
from yoke_core.domain.session_message_types import (
    SessionMessageError,
    timestamp,
    utc_now,
)
from yoke_core.domain.session_relay_evidence import redacted_evidence
from yoke_core.domain.session_relay_storage import marker
from yoke_core.domain.steering_fleet_plan_capacity import window_label
from yoke_core.domain.steering_fleet_report_limits import (
    MachinePlanLimit,
    load_plan_limits,
)


METER_EXHAUSTED_CODE = "meter_exhausted"
SKIP_METER_EXHAUSTED = "skipped_meter_exhausted"
SKIP_REASON_METER_EXHAUSTED = "model_meter_exhausted"
BLOCKED_METER_RESUME = "blocked-meter-exhausted"
_SKIP_ADAPTER_REVISION = "session-wake-meter-v1"
RECOVERY = (
    "Relaunch on a surface with headroom; this session cannot return "
    "until the meter resets."
)


@dataclass(frozen=True)
class MeterWall:
    """The published meter a wake would spend, when that meter is empty."""

    session_id: str
    project_id: int
    machine_id: str
    surface: str
    model: str
    meter: str
    pool: str
    remaining_percent: float
    resets_at: str | None
    window: str

    def refusal_message(self) -> str:
        quota = f"{int(round(self.remaining_percent))}%"
        reset = self.resets_at or "unknown"
        return (
            f"Native wake refused: meter {self.meter} ({self.window}) has "
            f"{quota} remaining, resets {reset}. {RECOVERY}"
        )


def _now_text(now: datetime | str) -> str:
    if isinstance(now, datetime):
        return timestamp(now)
    return str(now)


def pinned_model(row: Mapping[str, Any]) -> str:
    """The model a resume would re-send: served truth, else the launch ask."""
    served = str(row.get("model") or "").strip()
    if served:
        return served
    return str(row.get("requested_model") or "").strip()


def _session_row(conn: Any, session_id: str) -> dict[str, Any] | None:
    placeholder = marker(conn)
    row = conn.execute(
        "SELECT session_id, project_id, machine_id, executor_surface, "
        "model, requested_model FROM harness_sessions "
        f"WHERE session_id={placeholder}",
        (str(session_id),),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def _windows_for(
    limits: tuple[MachinePlanLimit, ...], *, machine_id: str, surface: str
) -> list[dict[str, Any]]:
    return [
        {
            "scope": row.scope,
            "status": row.status,
            "remaining_percent": row.remaining_percent,
            "meter": row.meter,
            "resets_at": row.resets_at,
            "window_kind": row.window_kind,
        }
        for row in limits
        if row.machine_id == machine_id and row.surface == surface
    ]


def _wall_from_windows(
    *,
    session_id: str,
    project_id: int,
    machine_id: str,
    surface: str,
    model: str,
    windows: list[dict[str, Any]],
) -> MeterWall | None:
    reading = pool_exhaustion(surface, model, windows)
    if not reading.exhausted:
        return None
    matched = next(
        (
            window
            for window in windows
            if str(window.get("scope") or "") == str(reading.pool or "")
        ),
        windows[0] if windows else {},
    )
    remaining = float(reading.remaining_percent or 0.0)
    resets_at = matched.get("resets_at")
    return MeterWall(
        session_id=session_id,
        project_id=int(project_id),
        machine_id=machine_id,
        surface=surface,
        model=model,
        meter=str(matched.get("meter") or "unknown"),
        pool=str(reading.pool or ""),
        remaining_percent=remaining,
        resets_at=resets_at if isinstance(resets_at, str) else None,
        window=window_label(
            str(matched.get("window_kind") or "unknown"),
            str(reading.pool or ""),
        ),
    )


def meter_wall(
    conn: Any,
    session_id: str,
    now: datetime | str,
    *,
    limits: tuple[MachinePlanLimit, ...] | None = None,
) -> MeterWall | None:
    """Return the empty meter a wake would spend, or None when it may proceed.

    Missing session, unnamed model, unreadable meter, and a pool that still
    has remaining quota are all None: this refuses only what it can prove.
    """
    row = _session_row(conn, session_id)
    if row is None:
        return None
    model = pinned_model(row)
    surface = str(row.get("executor_surface") or "").strip()
    machine_id = str(row.get("machine_id") or "").strip()
    project_id = row.get("project_id")
    if not model or not surface or not machine_id or project_id is None:
        return None
    stamp = _now_text(now)
    rows = (
        limits
        if limits is not None
        else load_plan_limits(conn, project_id=int(project_id), now=stamp)
    )
    return _wall_from_windows(
        session_id=str(session_id),
        project_id=int(project_id),
        machine_id=machine_id,
        surface=surface,
        model=model,
        windows=_windows_for(rows, machine_id=machine_id, surface=surface),
    )


def refuse_exhausted_wake(
    conn: Any, session_id: str, now: datetime | str
) -> SessionMessageError | None:
    """Named refusal for an operator-issued wake, or None when the meter allows it."""
    wall = meter_wall(conn, session_id, now)
    if wall is None:
        return None
    return SessionMessageError(METER_EXHAUSTED_CODE, wall.refusal_message())


def record_meter_exhausted_skip(
    conn: Any,
    candidate: Mapping[str, Any],
    wall: MeterWall,
    *,
    now: str,
) -> None:
    """Record why an automatic wake was not dispatched, without starting a native."""
    message_id = str(candidate["message_id"])
    session_id = str(candidate["session_id"])
    placeholder = marker(conn)
    conn.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id,message_id,target_session_id,attempt_kind,adapter_revision,"
        "started_at,completed_at,result_code,evidence) "
        f"VALUES ({','.join(placeholder for _ in range(9))}) "
        "ON CONFLICT(attempt_id) DO NOTHING",
        (
            str(
                uuid5(NAMESPACE_URL, f"yoke:wake-meter-skip:{message_id}:{session_id}")
            ),
            message_id,
            session_id,
            "wake_relay",
            _SKIP_ADAPTER_REVISION,
            now,
            now,
            SKIP_METER_EXHAUSTED,
            redacted_evidence(
                {
                    "result_code": SKIP_METER_EXHAUSTED,
                    "skip_reason": SKIP_REASON_METER_EXHAUSTED,
                    "requested_model": wall.model,
                    "surface": wall.surface,
                    "probe_detail": (
                        f"meter {wall.meter} ({wall.window}) "
                        f"{int(round(wall.remaining_percent))}% remaining, "
                        f"resets {wall.resets_at or 'unknown'}"
                    ),
                }
            ),
        ),
    )


def skip_exhausted_wake(
    conn: Any, candidate: Mapping[str, Any], now: datetime | str
) -> bool:
    """True when this wake must not start; the skip is recorded when so."""
    stamp = _now_text(now)
    wall = meter_wall(conn, str(candidate["session_id"]), stamp)
    if wall is None:
        return False
    record_meter_exhausted_skip(conn, candidate, wall, now=stamp)
    return True


def overlay_resume_state(
    conn: Any,
    session_id: str,
    resume_state: str | None,
    now: datetime | str | None = None,
) -> str | None:
    """Name a resumed death that will recur, leaving a transient death as-is."""
    if resume_state != "resumed-died":
        return resume_state
    if meter_wall(conn, session_id, now if now is not None else utc_now()) is None:
        return resume_state
    return BLOCKED_METER_RESUME


__all__ = [
    "BLOCKED_METER_RESUME",
    "METER_EXHAUSTED_CODE",
    "MeterWall",
    "RECOVERY",
    "SKIP_METER_EXHAUSTED",
    "SKIP_REASON_METER_EXHAUSTED",
    "meter_wall",
    "overlay_resume_state",
    "pinned_model",
    "record_meter_exhausted_skip",
    "refuse_exhausted_wake",
    "skip_exhausted_wake",
]
