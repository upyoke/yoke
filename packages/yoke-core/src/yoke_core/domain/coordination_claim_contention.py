"""Holder liveness and user-facing evidence for shared-operation waits."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from yoke_contracts.coordination_claim_recovery import operator_release_command


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
class ClaimContention:
    """One complete, repeatable contention report for a held claim."""

    claim_id: int
    project_id: int
    key: str
    holder_label: str
    acquired_at: str
    heartbeat_at: str | None
    heartbeat_age_seconds: int | None
    effective_stale_ttl_minutes: int
    holder_stale: bool
    operator_release_command: str

    @property
    def message(self) -> str:
        lead = (
            "Coordination claim wait refused"
            if self.holder_stale
            else "Waiting on coordination claim"
        )
        return (
            f"{lead} {self.key} (project {self.project_id}): already held by "
            f"{self.holder_label} since {self.acquired_at}; "
            f"heartbeat age {_age_label(self.heartbeat_age_seconds)} "
            f"(stale TTL {self.effective_stale_ttl_minutes}m). Human-only "
            f"operator release: `{self.operator_release_command}`."
        )

    def claim_evidence(self) -> dict[str, Any]:
        return {
            "id": self.claim_id,
            "key": self.key,
            "holder_session_id": self.holder_label,
            "acquired_at": self.acquired_at,
            "heartbeat_at": self.heartbeat_at,
            "heartbeat_age_seconds": self.heartbeat_age_seconds,
            "effective_stale_ttl_minutes": self.effective_stale_ttl_minutes,
            "holder_stale": self.holder_stale,
            "wait_message": self.message,
            "operator_release_command": self.operator_release_command,
        }


def describe_claim_contention(
    conn: Any,
    claim: Any,
    *,
    now: datetime | None = None,
) -> ClaimContention:
    """Classify a claim's heartbeat with the holder's canonical stale TTL.

    An item-owned hold has no session liveness to read — the item, not a
    session, is the holder — so it never reports stale and recovery stays
    with the operator.
    """
    from yoke_core.domain.session_reclaim_activity import read_activity_signals

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    item_owned = claim.owner_item_id is not None
    holder = (
        f"item {claim.owner_item_id}"
        if item_owned
        else f"session {claim.session_id}"
    )
    heartbeat_at = claim.last_heartbeat or claim.claimed_at
    heartbeat_age = _age_seconds(heartbeat_at, current)
    if item_owned:
        stale = False
        ttl = 0
    else:
        evidence = read_activity_signals(conn, str(claim.session_id))
        ttl = evidence.effective_ttl_minutes
        stale = (
            evidence.ended_at is not None
            or heartbeat_age is None
            or heartbeat_age >= ttl * 60
        )
    return ClaimContention(
        claim_id=int(claim.id),
        project_id=int(claim.project_id or 0),
        key=claim.key,
        holder_label=holder,
        acquired_at=str(claim.claimed_at),
        heartbeat_at=str(heartbeat_at) if heartbeat_at is not None else None,
        heartbeat_age_seconds=heartbeat_age,
        effective_stale_ttl_minutes=ttl,
        holder_stale=stale,
        operator_release_command=operator_release_command(
            claim.project_id or 0, claim.key
        ),
    )


def waiting_claim_evidence(
    claim: Any,
    contention: ClaimContention | None,
) -> dict[str, Any]:
    """Return structured wait output for a held shared-operation claim."""
    if contention is not None:
        return contention.claim_evidence()
    return {
        "id": int(claim.id),
        "key": claim.key,
        "holder_session_id": f"session {claim.session_id}",
        "acquired_at": str(claim.claimed_at),
        "heartbeat_at": claim.last_heartbeat,
    }


__all__ = [
    "ClaimContention",
    "describe_claim_contention",
    "waiting_claim_evidence",
]
