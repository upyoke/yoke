"""Holder liveness and user-facing evidence for coordination-lease waits."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from yoke_contracts.coordination_lease_recovery import operator_release_command
from yoke_core.domain.coordination_lease_record import OWNER_KIND_ITEM


def _timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_seconds(value: object, now: datetime) -> int | None:
    parsed = _timestamp(value)
    if parsed is None:
        return None
    return max(0, int((now - parsed).total_seconds()))


def _age_label(seconds: int | None) -> str:
    if seconds is None:
        return "unknown"
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    return f"{minutes // 60}h{minutes % 60:02d}m"


@dataclass(frozen=True)
class LeaseContention:
    """One complete, repeatable contention report for a held lease."""

    lease_id: int
    project_id: int
    lease_key: str
    holder_session_id: str
    acquired_at: str
    heartbeat_at: str | None
    heartbeat_age_seconds: int | None
    effective_stale_ttl_minutes: int
    holder_stale: bool
    operator_release_command: str

    @property
    def message(self) -> str:
        lead = (
            "Coordination lease wait refused"
            if self.holder_stale
            else "Waiting on coordination lease"
        )
        return (
            f"{lead} {self.lease_key} (project {self.project_id}): already held by "
            f"session {self.holder_session_id} since {self.acquired_at}; "
            f"heartbeat age {_age_label(self.heartbeat_age_seconds)} "
            f"(stale TTL {self.effective_stale_ttl_minutes}m). Human-only "
            f"operator release: `{self.operator_release_command}`."
        )

    def lease_evidence(self) -> dict[str, Any]:
        return {
            "id": self.lease_id,
            "key": self.lease_key,
            "holder_session_id": self.holder_session_id,
            "acquired_at": self.acquired_at,
            "heartbeat_at": self.heartbeat_at,
            "heartbeat_age_seconds": self.heartbeat_age_seconds,
            "effective_stale_ttl_minutes": self.effective_stale_ttl_minutes,
            "holder_stale": self.holder_stale,
            "wait_message": self.message,
            "operator_release_command": self.operator_release_command,
        }


def describe_lease_contention(
    conn: Any,
    lease: Any,
    *,
    now: datetime | None = None,
) -> LeaseContention:
    """Classify a lease heartbeat with the holder's canonical stale TTL."""
    from yoke_core.domain.session_reclaim_activity import read_activity_signals

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    holder = (
        f"item {lease.owner_item_id}"
        if getattr(lease, "owner_kind", None) == OWNER_KIND_ITEM
        else str(lease.owner_session_id or lease.session_id)
    )
    heartbeat_at = lease.heartbeat_at or lease.acquired_at
    heartbeat_age = _age_seconds(heartbeat_at, current)
    if getattr(lease, "owner_kind", None) == OWNER_KIND_ITEM:
        stale = False
        ttl = 0
    else:
        evidence = read_activity_signals(
            conn, str(lease.owner_session_id or lease.session_id),
        )
        ttl = evidence.effective_ttl_minutes
        stale = (
            evidence.ended_at is not None
            or heartbeat_age is None
            or heartbeat_age >= ttl * 60
        )
    return LeaseContention(
        lease_id=int(lease.id),
        project_id=int(lease.project_id),
        lease_key=str(lease.lease_key),
        holder_session_id=holder,
        acquired_at=str(lease.acquired_at),
        heartbeat_at=str(heartbeat_at) if heartbeat_at is not None else None,
        heartbeat_age_seconds=heartbeat_age,
        effective_stale_ttl_minutes=ttl,
        holder_stale=stale,
        operator_release_command=operator_release_command(
            lease.project_id,
            lease.lease_key,
        ),
    )


def waiting_lease_evidence(
    lease: Any,
    contention: LeaseContention | None,
) -> dict[str, Any]:
    """Return structured wait output, preserving the legacy lease keys."""
    if contention is not None:
        return contention.lease_evidence()
    return {
        "id": int(lease.id),
        "key": str(lease.lease_key),
        "holder_session_id": str(lease.session_id),
        "acquired_at": str(lease.acquired_at),
        "heartbeat_at": lease.heartbeat_at,
    }


__all__ = [
    "LeaseContention",
    "describe_lease_contention",
    "waiting_lease_evidence",
]
