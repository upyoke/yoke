"""Core acquire, heartbeat, release, and read API for coordination leases."""

from __future__ import annotations

from typing import Any, Dict, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.coordination_lease_record import (
    SELECT_COLUMNS,
    Lease,
    resolve_typed_owner,
    row_to_lease,
)
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

    def __init__(self, message: str, *, contention: Any = None) -> None:
        super().__init__(message)
        self.contention = contention


class LeaseStaleHolderError(LeaseHeldError):
    """Raised when the current holder is beyond its session stale TTL."""


class LeaseNotFoundError(LeaseError):
    """Raised when the caller names a lease that does not exist."""


class LeaseReleasedError(LeaseError):
    """Raised when a heartbeat targets an already-released lease."""


class LeaseHookContextError(LeaseError):
    """Raised when the human-only operator override runs in a hook context."""


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def active_lease(
    conn: Any,
    project_id: str | int,
    lease_key: str,
    *,
    for_update: bool = False,
) -> Optional[Lease]:
    """Return the currently-held lease for ``(project_id, lease_key)``, if any."""
    p = _placeholder(conn)
    numeric_project_id = resolve_project_id(conn, project_id)
    suffix = " FOR UPDATE" if for_update and db_backend.connection_is_postgres(conn) else ""
    row = conn.execute(
        f"SELECT {SELECT_COLUMNS} "
        "FROM coordination_leases "
        f"WHERE project_id = {p} AND lease_key = {p} AND released_at IS NULL "
        f"ORDER BY acquired_at DESC, id DESC LIMIT 1{suffix}",
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


def _held_error(conn: Any, lease: Lease) -> LeaseHeldError:
    from yoke_core.domain.coordination_lease_contention import (
        describe_lease_contention,
    )

    contention = describe_lease_contention(conn, lease)
    error_type = LeaseStaleHolderError if contention.holder_stale else LeaseHeldError
    return error_type(contention.message, contention=contention)


def acquire_lease(
    conn: Any,
    project_id: str | int,
    lease_key: str,
    session_id: str,
    *,
    actor_id: Optional[str] = None,
    owner_kind: Optional[str] = None,
    owner_item_id: Optional[int] = None,
    owner_session_id: Optional[str] = None,
    owner_work_claim_id: Optional[int] = None,
    now: Optional[str] = None,
    commit: bool = True,
) -> Lease:
    """Acquire an exclusive lease on ``(project_id, lease_key)``.

    Conflicts surface as :class:`LeaseHeldError` (not raw SQLite errors) and
    carry the current holder's context. ``heartbeat_at`` is set to the
    acquisition timestamp so doctor liveness queries treat a fresh lease as
    fully heartbeated until the first explicit heartbeat lands.
    """
    now = now or iso8601_now()
    p = _placeholder(conn)
    kind, item_id, session_owner, claim_id = resolve_typed_owner(
        owner_kind,
        session_id=session_id,
        owner_item_id=owner_item_id,
        owner_session_id=owner_session_id,
        owner_work_claim_id=owner_work_claim_id,
    )
    numeric_project_id = resolve_project_id(conn, project_id)
    existing = active_lease(conn, numeric_project_id, lease_key)
    if existing is not None:
        raise _held_error(conn, existing)
    use_savepoint = db_backend.connection_is_postgres(conn)
    if use_savepoint:
        conn.execute("SAVEPOINT coordination_lease_acquire")
    try:
        cur = conn.execute(
            "INSERT INTO coordination_leases "
            "(project_id, lease_key, session_id, actor_id, acquired_at, "
            "heartbeat_at, owner_kind, owner_item_id, owner_session_id, "
            "owner_work_claim_id) "
            f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}) "
            "RETURNING id",
            (
                numeric_project_id, lease_key, session_id, actor_id, now, now,
                kind, item_id, session_owner, claim_id,
            ),
        )
    except db_backend.integrity_error_types(conn) as exc:
        if use_savepoint:
            conn.execute("ROLLBACK TO SAVEPOINT coordination_lease_acquire")
            conn.execute("RELEASE SAVEPOINT coordination_lease_acquire")
        current = active_lease(conn, numeric_project_id, lease_key)
        if current is not None:
            raise _held_error(conn, current) from exc
        raise LeaseHeldError(
            f"Lease {numeric_project_id}:{lease_key} already held (unknown holder)"
        ) from exc
    if use_savepoint:
        conn.execute("RELEASE SAVEPOINT coordination_lease_acquire")
    lease_id = int(cur.fetchone()[0])
    if commit:
        conn.commit()
    lease = get_lease(conn, lease_id)
    _emit_lease_event(
        LEASE_ACQUIRED_EVENT,
        "INFO",
        lease,
        context={"actor_id": actor_id},
        conn=None if commit else conn,
    )
    return lease


def heartbeat_lease(
    conn: Any,
    lease_id: int,
    *,
    now: Optional[str] = None,
    commit: bool = True,
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
    if commit:
        conn.commit()
    refreshed = get_lease(conn, lease_id)
    event_conn = None if commit else conn
    _emit_lease_event(LEASE_HEARTBEATED_EVENT, "INFO", refreshed, conn=event_conn)
    return refreshed


def release_lease(
    conn: Any,
    lease_id: int,
    reason: str,
    *,
    now: Optional[str] = None,
    released_by_session_id: Optional[str] = None,
    released_by_actor_id: Optional[str] = None,
    commit: bool = True,
) -> Lease:
    """Release a held lease. Idempotent — re-releasing returns unchanged."""
    now = now or iso8601_now()
    p = _placeholder(conn)
    lease = get_lease(conn, lease_id)
    if not lease.is_active:
        return lease
    conn.execute(
        f"UPDATE coordination_leases SET released_at = {p}, release_reason = {p}, "
        f"released_by_session_id = {p}, released_by_actor_id = {p} "
        f"WHERE id = {p} AND released_at IS NULL",
        (now, reason, released_by_session_id, released_by_actor_id, lease_id),
    )
    if commit:
        conn.commit()
    released = get_lease(conn, lease_id)
    _emit_lease_event(
        LEASE_RELEASED_EVENT,
        "INFO",
        released,
        context={"release_reason": reason},
        conn=None if commit else conn,
    )
    return released


def _emit_lease_event(
    name: str,
    severity: str,
    lease: Lease,
    *,
    context: Optional[Dict[str, Any]] = None,
    conn: Optional[Any] = None,
) -> None:
    """Fire a lease-lifecycle event via the shared emitter, best-effort."""
    payload: Dict[str, Any] = {
        "lease_id": lease.id,
        "project_id": lease.project_id,
        "lease_key": lease.lease_key,
        "session_id": lease.session_id,
        "owner_kind": lease.owner_kind,
        "owner_item_id": lease.owner_item_id,
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
            conn=conn,
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
    "LeaseStaleHolderError",
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
