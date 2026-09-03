"""Steerer-managed per-machine surface disable marks.

v0 is a manual circuit breaker: one live disabled row per (machine, surface).
Tripping, probing, and recovery stay steering judgment — this module stores
the mark and names the enable command when a launch or native resume refuses.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from yoke_contracts.session_control.surface_policy import (
    SURFACE_POLICY_STATE_DISABLED,
)
from yoke_core.domain.session_launch_capacity import (
    MACHINE_AT_CAPACITY,
    capacity_refusal,
)
from yoke_core.domain.session_launch_store import marker, utc_now
from yoke_core.domain.session_launch_types import LaunchPreview, SessionLaunchError


SURFACE_DISABLED_REJECTION = "surface_disabled"
WAKE_SKIP_SURFACE_DISABLED = "skipped_surface_disabled"


class SurfacePolicyError(SessionLaunchError):
    """A surface-policy mutation or lookup was refused with a typed code."""


def enable_command(machine_id: str, surface: str) -> str:
    return (
        "yoke session-control surface-policy enable "
        f"--machine {machine_id} --surface {surface}"
    )


def _row(row: Any) -> dict[str, Any]:
    record = dict(row)
    return {
        "mark_id": str(record["mark_id"]),
        "machine_id": str(record["machine_id"]),
        "surface": str(record["surface"]),
        "state": str(record["state"]),
        "reason": str(record["reason"]),
        "evidence": record.get("evidence"),
        "set_by_actor_id": int(record["set_by_actor_id"]),
        "set_by_session_id": record.get("set_by_session_id"),
        "created_at": str(record["created_at"]),
        "cleared_at": record.get("cleared_at"),
        "cleared_by_actor_id": record.get("cleared_by_actor_id"),
    }


def live_mark(conn: Any, machine_id: str, surface: str) -> dict[str, Any] | None:
    """Return the live disable mark for one (machine, surface), if any."""
    placeholder = marker(conn)
    row = conn.execute(
        "SELECT mark_id, machine_id, surface, state, reason, evidence, "
        "set_by_actor_id, set_by_session_id, created_at, cleared_at, "
        "cleared_by_actor_id FROM session_surface_policies "
        f"WHERE machine_id = {placeholder} AND surface = {placeholder} "
        "AND cleared_at IS NULL",
        (str(machine_id), str(surface)),
    ).fetchone()
    return _row(row) if row is not None else None


def list_marks(
    conn: Any,
    *,
    machine_id: str | None = None,
    surface: str | None = None,
    include_cleared: bool = False,
) -> list[dict[str, Any]]:
    placeholder = marker(conn)
    clauses: list[str] = []
    params: list[Any] = []
    if machine_id:
        clauses.append(f"machine_id = {placeholder}")
        params.append(str(machine_id))
    if surface:
        clauses.append(f"surface = {placeholder}")
        params.append(str(surface))
    if not include_cleared:
        clauses.append("cleared_at IS NULL")
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        "SELECT mark_id, machine_id, surface, state, reason, evidence, "
        "set_by_actor_id, set_by_session_id, created_at, cleared_at, "
        "cleared_by_actor_id FROM session_surface_policies"
        + where
        + " ORDER BY created_at DESC, mark_id ASC",
        tuple(params),
    ).fetchall()
    return [_row(row) for row in rows]


def set_mark(
    conn: Any,
    *,
    machine_id: str,
    surface: str,
    reason: str,
    actor_id: int,
    session_id: str | None,
    evidence: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Disable one (machine, surface), replacing any live mark in place."""
    current = now or utc_now()
    existing = live_mark(conn, machine_id, surface)
    placeholder = marker(conn)
    if existing is not None:
        conn.execute(
            "UPDATE session_surface_policies SET reason = "
            + placeholder
            + ", evidence = "
            + placeholder
            + ", set_by_actor_id = "
            + placeholder
            + ", set_by_session_id = "
            + placeholder
            + ", created_at = "
            + placeholder
            + f" WHERE mark_id = {placeholder}",
            (reason, evidence, int(actor_id), session_id, current, existing["mark_id"]),
        )
        mark = live_mark(conn, machine_id, surface)
        if mark is None:
            raise SurfacePolicyError("mark_missing", "live mark vanished during update")
        return mark
    mark_id = str(uuid4())
    conn.execute(
        "INSERT INTO session_surface_policies "
        "(mark_id, machine_id, surface, state, reason, evidence, "
        "set_by_actor_id, set_by_session_id, created_at) VALUES ("
        + ", ".join(placeholder for _ in range(9))
        + ")",
        (
            mark_id,
            str(machine_id),
            str(surface),
            SURFACE_POLICY_STATE_DISABLED,
            reason,
            evidence,
            int(actor_id),
            session_id,
            current,
        ),
    )
    return {
        "mark_id": mark_id,
        "machine_id": str(machine_id),
        "surface": str(surface),
        "state": SURFACE_POLICY_STATE_DISABLED,
        "reason": reason,
        "evidence": evidence,
        "set_by_actor_id": int(actor_id),
        "set_by_session_id": session_id,
        "created_at": current,
        "cleared_at": None,
        "cleared_by_actor_id": None,
    }


def clear_mark(
    conn: Any,
    *,
    machine_id: str,
    surface: str,
    actor_id: int,
    now: str | None = None,
) -> dict[str, Any]:
    existing = live_mark(conn, machine_id, surface)
    if existing is None:
        raise SurfacePolicyError(
            "mark_not_found",
            f"no live disable mark for {surface} on machine {machine_id}; "
            "list with `yoke session-control surface-policy list "
            f"--machine {machine_id}`",
        )
    current = now or utc_now()
    placeholder = marker(conn)
    conn.execute(
        "UPDATE session_surface_policies SET cleared_at = "
        + placeholder
        + ", cleared_by_actor_id = "
        + placeholder
        + f" WHERE mark_id = {placeholder}",
        (current, int(actor_id), existing["mark_id"]),
    )
    existing["cleared_at"] = current
    existing["cleared_by_actor_id"] = int(actor_id)
    return existing


def mark_refusal_text(mark: dict[str, Any]) -> str:
    machine_id = str(mark["machine_id"])
    surface = str(mark["surface"])
    return (
        f"{surface} is disabled on machine {machine_id}: {mark['reason']}. "
        f"Enable with: {enable_command(machine_id, surface)}"
    )


_CREATE_NONE_REASONS = {
    "codex-desktop": (
        "codex-desktop declares create=none because its owning desktop app "
        "holds the only writer lease, so Yoke cannot create or wake that "
        "conversation. Recovery: request codex-cli for Yoke-created work."
    ),
    "claude-desktop": (
        "claude-desktop declares create=none because the Claude adapter "
        "creates only claude-cli sessions; desktop has no native create "
        "route. Recovery: request claude-cli for Yoke-created work."
    ),
}


def launch_refusal_message(conn: Any, preview: LaunchPreview) -> str:
    prefix = f"launch refused with outcome {preview.outcome}"
    if preview.outcome == "unsupported_surface":
        surface = preview.requested_surface
        reason = _CREATE_NONE_REASONS.get(
            surface,
            f"{surface} declares create=none. Recovery: choose a surface "
            "whose session-control create capability is supported and retry.",
        )
        return f"{prefix}: {reason}"
    if preview.outcome == MACHINE_AT_CAPACITY:
        return f"{prefix}: {capacity_refusal(preview.machine_capacity)}"
    if preview.placement_reason:
        # Placement already refused in a full sentence naming each machine it
        # weighed; the rejection codes describe eligibility, which passed.
        return f"{prefix}: {preview.placement_reason}"
    if SURFACE_DISABLED_REJECTION not in preview.rejection_codes:
        codes = ", ".join(preview.rejection_codes) or "no relay evidence"
        return f"{prefix}: {codes}"
    considered = set(preview.considered_machine_ids)
    details = [
        mark_refusal_text(mark)
        for mark in list_marks(conn, surface=preview.requested_surface)
        if not considered or mark["machine_id"] in considered
    ]
    if not details:
        details = [mark_refusal_text(mark) for mark in list_marks(conn)]
    return f"{prefix}: {'; '.join(details) or SURFACE_DISABLED_REJECTION}"


__all__ = [
    "SURFACE_DISABLED_REJECTION",
    "SurfacePolicyError",
    "WAKE_SKIP_SURFACE_DISABLED",
    "clear_mark",
    "enable_command",
    "launch_refusal_message",
    "list_marks",
    "live_mark",
    "mark_refusal_text",
    "set_mark",
]
