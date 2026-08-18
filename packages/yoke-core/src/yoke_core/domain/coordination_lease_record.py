"""Typed owner record for ``coordination_leases`` rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


OWNER_KIND_ITEM = "item"
OWNER_KIND_SESSION = "session"
OWNER_KIND_PROCESS = "process"
OWNER_KINDS = frozenset(
    {OWNER_KIND_ITEM, OWNER_KIND_SESSION, OWNER_KIND_PROCESS}
)

SELECT_COLUMNS = (
    "id, project_id, lease_key, session_id, acquired_at, heartbeat_at, "
    "actor_id, released_at, release_reason, owner_kind, owner_item_id, "
    "owner_session_id, owner_work_claim_id, released_by_session_id, "
    "released_by_actor_id"
)


@dataclass(frozen=True)
class Lease:
    """Plain record describing a coordination-lease row."""

    id: int
    project_id: int
    lease_key: str
    session_id: str
    acquired_at: str
    heartbeat_at: Optional[str] = None
    actor_id: Optional[str] = None
    released_at: Optional[str] = None
    release_reason: Optional[str] = None
    owner_kind: str = OWNER_KIND_SESSION
    owner_item_id: Optional[int] = None
    owner_session_id: Optional[str] = None
    owner_work_claim_id: Optional[int] = None
    released_by_session_id: Optional[str] = None
    released_by_actor_id: Optional[str] = None

    @property
    def is_active(self) -> bool:
        return self.released_at is None


def row_to_lease(row: Any) -> Lease:
    owner_item = row["owner_item_id"]
    owner_claim = row["owner_work_claim_id"]
    return Lease(
        id=row["id"],
        project_id=int(row["project_id"]),
        lease_key=row["lease_key"],
        session_id=row["session_id"],
        acquired_at=row["acquired_at"],
        heartbeat_at=row["heartbeat_at"],
        actor_id=row["actor_id"],
        released_at=row["released_at"],
        release_reason=row["release_reason"],
        owner_kind=str(row["owner_kind"] or OWNER_KIND_SESSION),
        owner_item_id=int(owner_item) if owner_item is not None else None,
        owner_session_id=row["owner_session_id"],
        owner_work_claim_id=(
            int(owner_claim) if owner_claim is not None else None
        ),
        released_by_session_id=row["released_by_session_id"],
        released_by_actor_id=row["released_by_actor_id"],
    )


def resolve_typed_owner(
    owner_kind: Optional[str],
    *,
    session_id: str,
    owner_item_id: Optional[int] = None,
    owner_session_id: Optional[str] = None,
    owner_work_claim_id: Optional[int] = None,
) -> tuple[str, Optional[int], Optional[str], Optional[int]]:
    """Return the closed owner tuple, or raise ``ValueError``."""
    kind = owner_kind or OWNER_KIND_SESSION
    if kind not in OWNER_KINDS:
        raise ValueError(f"owner_kind must be one of {sorted(OWNER_KINDS)}")
    if kind == OWNER_KIND_ITEM:
        if owner_item_id is None:
            raise ValueError("item-owned lease requires owner_item_id")
        return kind, int(owner_item_id), None, None
    if kind == OWNER_KIND_PROCESS:
        if owner_work_claim_id is None:
            raise ValueError("process-owned lease requires owner_work_claim_id")
        return kind, None, None, int(owner_work_claim_id)
    held = owner_session_id or session_id
    if not held:
        raise ValueError("session-owned lease requires owner_session_id")
    return kind, None, str(held), None


def lease_as_dict(lease: Lease) -> dict[str, Any]:
    return {
        "id": int(lease.id),
        "project_id": str(lease.project_id),
        "lease_key": str(lease.lease_key),
        "session_id": str(lease.session_id),
        "actor_id": lease.actor_id,
        "acquired_at": lease.acquired_at,
        "heartbeat_at": lease.heartbeat_at,
        "released_at": lease.released_at,
        "release_reason": lease.release_reason,
        "owner_kind": lease.owner_kind,
        "owner_item_id": lease.owner_item_id,
        "owner_session_id": lease.owner_session_id,
        "owner_work_claim_id": lease.owner_work_claim_id,
        "released_by_session_id": lease.released_by_session_id,
        "released_by_actor_id": lease.released_by_actor_id,
    }


__all__ = [
    "OWNER_KIND_ITEM",
    "OWNER_KIND_PROCESS",
    "OWNER_KIND_SESSION",
    "OWNER_KINDS",
    "SELECT_COLUMNS",
    "Lease",
    "lease_as_dict",
    "resolve_typed_owner",
    "row_to_lease",
]
