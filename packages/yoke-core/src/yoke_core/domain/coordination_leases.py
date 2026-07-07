"""Coordination-lease primitive for Yoke.

A ``coordination_leases`` row is an exclusive, project-scoped, shared-operation
lease keyed on ``(project_id, lease_key)``. The migration consumer scopes
per-model via ``LIVE_DB_MIGRATION:<model_name>``; future shared-operation
consumers pick their own key conventions without adding another lock table.

Coordination leases are NOT work claims (item/process occupancy lives in
``work_claims``) and they are NOT path claims (repo mutation authority lives
in ``path_claims``). They cover dangerous shared-state operations whose
serial ordering is required for correctness — live DB schema mutation is the
first such operation.

This module owns the core acquire/heartbeat/release/read API plus shared
event-emission helpers. Listing/diagnostic helpers live in
:mod:`yoke_core.domain.coordination_leases_listing`; the human-only
operator override lives in :mod:`yoke_core.domain.coordination_leases_operator`.
Both are re-exported here so existing call sites keep their imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.project_identity import resolve_project_id


OPERATOR_LEASE_RELEASE_EVENT = "OperatorLeaseRelease"
LEASE_ACQUIRED_EVENT = "LeaseAcquired"
LEASE_HEARTBEATED_EVENT = "LeaseHeartbeated"
LEASE_RELEASED_EVENT = "LeaseReleased"


class LeaseError(Exception):
    """Base class for coordination-lease errors."""


class LeaseHeldError(LeaseError):
    """Raised when an acquire loses to a still-live lease on the same key."""


class LeaseNotFoundError(LeaseError):
    """Raised when the caller names a lease that does not exist."""


class LeaseReleasedError(LeaseError):
    """Raised when a heartbeat targets an already-released lease."""


class LeaseHookContextError(LeaseError):
    """Raised when the human-only operator override runs in a hook context."""


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

    @property
    def is_active(self) -> bool:
        return self.released_at is None


SELECT_COLUMNS = (
    "id, project_id, lease_key, session_id, acquired_at, heartbeat_at, "
    "actor_id, released_at, release_reason"
)


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def row_to_lease(row: Any) -> Lease:
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
    )


def active_lease(
    conn: Any,
    project_id: str | int,
    lease_key: str,
) -> Optional[Lease]:
    """Return the currently-held lease for ``(project_id, lease_key)``, if any."""
    p = _placeholder(conn)
    numeric_project_id = resolve_project_id(conn, project_id)
    row = conn.execute(
        f"SELECT {SELECT_COLUMNS} "
        "FROM coordination_leases "
        f"WHERE project_id = {p} AND lease_key = {p} AND released_at IS NULL "
        "ORDER BY acquired_at DESC, id DESC LIMIT 1",
        (numeric_project_id, lease_key),
    ).fetchone()
    return row_to_lease(row) if row is not None else None


def get_lease(conn: Any, lease_id: int) -> Lease:
    """Fetch a lease by id or raise :class:`LeaseNotFoundError`."""
    p = _placeholder(conn)
    row = conn.execute(
        f"SELECT {SELECT_COLUMNS} FROM coordination_leases WHERE id = {p}",
        (lease_id,),
    ).fetchone()
    if row is None:
        raise LeaseNotFoundError(f"Coordination lease id={lease_id} not found")
    return row_to_lease(row)


def acquire_lease(
    conn: Any,
    project_id: str | int,
    lease_key: str,
    session_id: str,
    *,
    actor_id: Optional[str] = None,
    now: Optional[str] = None,
) -> Lease:
    """Acquire an exclusive lease on ``(project_id, lease_key)``.

    Conflicts surface as :class:`LeaseHeldError` (not raw SQLite errors) and
    carry the current holder's context. ``heartbeat_at`` is set to the
    acquisition timestamp so doctor liveness queries treat a fresh lease as
    fully heartbeated until the first explicit heartbeat lands.
    """
    now = now or iso8601_now()
    p = _placeholder(conn)
    numeric_project_id = resolve_project_id(conn, project_id)
    existing = active_lease(conn, numeric_project_id, lease_key)
    if existing is not None:
        raise LeaseHeldError(
            f"Lease {numeric_project_id}:{lease_key} already held "
            f"(session={existing.session_id}, acquired_at={existing.acquired_at})"
        )
    try:
        cur = conn.execute(
            "INSERT INTO coordination_leases "
            "(project_id, lease_key, session_id, actor_id, acquired_at, heartbeat_at) "
            f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}) RETURNING id",
            (numeric_project_id, lease_key, session_id, actor_id, now, now),
        )
    except db_backend.integrity_error_types(conn) as exc:
        current = active_lease(conn, numeric_project_id, lease_key)
        holder = (
            f"session={current.session_id}, acquired_at={current.acquired_at}"
            if current is not None
            else "unknown holder"
        )
        raise LeaseHeldError(
            f"Lease {numeric_project_id}:{lease_key} already held ({holder})"
        ) from exc
    lease_id = int(cur.fetchone()[0])
    conn.commit()
    lease = get_lease(conn, lease_id)
    _emit_lease_event(
        LEASE_ACQUIRED_EVENT, "INFO", lease,
        context={"actor_id": actor_id},
    )
    return lease


def heartbeat_lease(
    conn: Any,
    lease_id: int,
    *,
    now: Optional[str] = None,
) -> Lease:
    """Refresh ``heartbeat_at`` on a held lease.

    Refuses missing rows with :class:`LeaseNotFoundError` and released rows
    with :class:`LeaseReleasedError` so callers cannot silently resurrect or
    decorate stale rows.
    """
    now = now or iso8601_now()
    p = _placeholder(conn)
    lease = get_lease(conn, lease_id)
    if not lease.is_active:
        raise LeaseReleasedError(
            f"Coordination lease id={lease_id} is released "
            f"(released_at={lease.released_at}); heartbeat refused"
        )
    conn.execute(
        f"UPDATE coordination_leases SET heartbeat_at = {p} "
        f"WHERE id = {p} AND released_at IS NULL",
        (now, lease_id),
    )
    conn.commit()
    refreshed = get_lease(conn, lease_id)
    _emit_lease_event(LEASE_HEARTBEATED_EVENT, "INFO", refreshed)
    return refreshed


def release_lease(
    conn: Any,
    lease_id: int,
    reason: str,
    *,
    now: Optional[str] = None,
) -> Lease:
    """Release a held lease. Idempotent — re-releasing returns unchanged."""
    now = now or iso8601_now()
    p = _placeholder(conn)
    lease = get_lease(conn, lease_id)
    if not lease.is_active:
        return lease
    conn.execute(
        f"UPDATE coordination_leases SET released_at = {p}, release_reason = {p} "
        f"WHERE id = {p} AND released_at IS NULL",
        (now, reason, lease_id),
    )
    conn.commit()
    released = get_lease(conn, lease_id)
    _emit_lease_event(
        LEASE_RELEASED_EVENT, "INFO", released,
        context={"release_reason": reason},
    )
    return released


def _emit_lease_event(
    name: str,
    severity: str,
    lease: Lease,
    *,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    """Fire a lease-lifecycle event via the shared emitter, best-effort."""
    payload: Dict[str, Any] = {
        "lease_id": lease.id,
        "project_id": lease.project_id,
        "lease_key": lease.lease_key,
        "session_id": lease.session_id,
        "actor_id": lease.actor_id,
        "acquired_at": lease.acquired_at,
        "heartbeat_at": lease.heartbeat_at,
        "released_at": lease.released_at,
    }
    if context:
        payload.update(context)
    try:
        from yoke_core.domain.events import emit_event as _emit

        _emit(
            name,
            event_kind="lifecycle",
            event_type="lease_lifecycle",
            source_type="api",
            session_id=lease.session_id,
            project=lease.project_id,
            severity=severity,
            outcome="completed",
            context=payload,
        )
    except Exception:
        # Best-effort telemetry; the lifecycle row remains the source of truth.
        pass


def list_leases(*args: Any, **kwargs: Any) -> Any:
    """Compatibility wrapper for the listing sibling module."""
    from yoke_core.domain.coordination_leases_listing import (
        list_leases as _list_leases,
    )

    return _list_leases(*args, **kwargs)


def stale_lease_candidates(*args: Any, **kwargs: Any) -> Any:
    """Compatibility wrapper for the listing sibling module."""
    from yoke_core.domain.coordination_leases_listing import (
        stale_lease_candidates as _stale_lease_candidates,
    )

    return _stale_lease_candidates(*args, **kwargs)


def operator_release(*args: Any, **kwargs: Any) -> Any:
    """Compatibility wrapper for the human-only operator sibling module."""
    from yoke_core.domain.coordination_leases_operator import (
        operator_release as _operator_release,
    )

    return _operator_release(*args, **kwargs)


__all__ = [
    "LEASE_ACQUIRED_EVENT",
    "LEASE_HEARTBEATED_EVENT",
    "LEASE_RELEASED_EVENT",
    "Lease",
    "LeaseError",
    "LeaseHeldError",
    "LeaseHookContextError",
    "LeaseNotFoundError",
    "LeaseReleasedError",
    "OPERATOR_LEASE_RELEASE_EVENT",
    "SELECT_COLUMNS",
    "acquire_lease",
    "active_lease",
    "get_lease",
    "heartbeat_lease",
    "list_leases",
    "operator_release",
    "release_lease",
    "row_to_lease",
    "stale_lease_candidates",
]
