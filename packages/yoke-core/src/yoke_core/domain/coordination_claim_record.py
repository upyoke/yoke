"""Row shape for a shared-operation work claim.

A coordination claim is an ordinary ``work_claims`` row whose target kind
names a shared resource rather than a unit of backlog work. This module
decodes such a row into the record every consumer reads, resolving the
holder's actor from the session that took the claim rather than storing a
second copy of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from yoke_core.domain.coordination_claim_keys import key_for_target
from yoke_core.domain.work_claim_targets import (
    TARGET_KIND_MIGRATION_SERIALIZATION,
    WorkClaimTarget,
    decode_scope,
    is_sticky,
)

SELECT_COLUMNS = (
    "wc.id, wc.session_id, wc.target_kind, wc.scope, wc.claimed_at, "
    "wc.last_heartbeat, wc.released_at, wc.release_reason, "
    "wc.release_reason_intent, wc.reason, hs.actor_id"
)
FROM_CLAUSE = (
    "FROM work_claims wc "
    "LEFT JOIN harness_sessions hs ON hs.session_id = wc.session_id"
)


@dataclass(frozen=True)
class CoordinationClaim:
    """One shared-operation claim, live or settled."""

    id: int
    target: WorkClaimTarget
    session_id: str
    claimed_at: str
    last_heartbeat: Optional[str] = None
    actor_id: Optional[str] = None
    released_at: Optional[str] = None
    release_reason: Optional[str] = None
    release_reason_intent: Optional[str] = None
    reason: Optional[str] = None

    @property
    def is_active(self) -> bool:
        return self.released_at is None

    @property
    def key(self) -> str:
        return key_for_target(self.target)

    @property
    def kind(self) -> str:
        return self.target.kind

    @property
    def project_id(self) -> Optional[int]:
        return self.target.project_id

    @property
    def owner_item_id(self) -> Optional[int]:
        """The item that owns this hold, for the kinds that name one."""
        if self.target.kind == TARGET_KIND_MIGRATION_SERIALIZATION:
            return self.target.item_id
        return None

    @property
    def sticky(self) -> bool:
        return is_sticky(self.target.kind)


def row_to_claim(row: Any) -> CoordinationClaim:
    """Decode one joined ``work_claims`` row."""
    actor = row["actor_id"]
    return CoordinationClaim(
        id=int(row["id"]),
        target=WorkClaimTarget(
            kind=str(row["target_kind"]),
            scope=decode_scope(row["scope"]),
        ),
        session_id=str(row["session_id"]),
        claimed_at=str(row["claimed_at"]),
        last_heartbeat=row["last_heartbeat"],
        actor_id=str(actor) if actor is not None else None,
        released_at=row["released_at"],
        release_reason=row["release_reason"],
        release_reason_intent=row["release_reason_intent"],
        reason=row["reason"],
    )


def claim_as_dict(claim: CoordinationClaim) -> dict[str, Any]:
    """Return the JSON boundary shape for one coordination claim."""
    return {
        "id": int(claim.id),
        "key": claim.key,
        "target_kind": claim.target.kind,
        "scope": dict(claim.target.scope),
        "project_id": claim.project_id,
        "session_id": claim.session_id,
        "actor_id": claim.actor_id,
        "owner_item_id": claim.owner_item_id,
        "sticky": claim.sticky,
        "claimed_at": claim.claimed_at,
        "last_heartbeat": claim.last_heartbeat,
        "released_at": claim.released_at,
        "release_reason": claim.release_reason,
        "release_reason_intent": claim.release_reason_intent,
    }


__all__ = [
    "FROM_CLAUSE",
    "SELECT_COLUMNS",
    "CoordinationClaim",
    "claim_as_dict",
    "row_to_claim",
]
