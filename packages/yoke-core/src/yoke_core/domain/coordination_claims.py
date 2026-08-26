"""Acquire, heartbeat, release, and read shared-operation work claims.

A shared-operation claim serializes a resource that is not a unit of
backlog work — migration territory for one model, one physical test
machine, one private-route qualification grant. It is an ordinary
``work_claims`` row: the same session binding, heartbeat, typed target,
and telemetry the backlog claims use. What separates the sticky kinds is
liveness policy, which
:data:`yoke_core.domain.work_claim_targets.STICKY_TARGET_KINDS` owns and
the stale-session sweep and session-end release consult: the resource
keeps operating after the session that took it goes quiet, so recovery
is the audited human operator release rather than an automatic reclaim.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.coordination_claim_record import (
    FROM_CLAUSE,
    SELECT_COLUMNS,
    CoordinationClaim,
    row_to_claim,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.work_claim_target_sql import conflict_match_clause
from yoke_core.domain.work_claim_targets import WorkClaimTarget

OPERATOR_LEASE_RELEASE_EVENT = "OperatorLeaseRelease"
LEASE_ACQUIRED_EVENT = "LeaseAcquired"
LEASE_HEARTBEATED_EVENT = "LeaseHeartbeated"
LEASE_RELEASED_EVENT = "LeaseReleased"

#: ``work_claims.release_reason`` is a closed schema vocabulary; the
#: caller's own words land in ``release_reason_intent`` beside it.
DEFAULT_RELEASE_REASON = "released"


class CoordinationClaimError(Exception):
    """Base class for shared-operation claim errors."""


class CoordinationClaimHeldError(CoordinationClaimError):
    """Raised when an acquire loses to a still-live holder."""

    def __init__(self, message: str, *, contention: Any = None) -> None:
        super().__init__(message)
        self.contention = contention


class CoordinationClaimStaleHolderError(CoordinationClaimHeldError):
    """Raised when the current holder is beyond its session stale TTL."""


class CoordinationClaimNotFoundError(CoordinationClaimError):
    """Raised when the caller names a claim that does not exist."""


class CoordinationClaimReleasedError(CoordinationClaimError):
    """Raised when a heartbeat targets an already-released claim."""


class CoordinationClaimHookContextError(CoordinationClaimError):
    """Raised when the human-only operator override runs in a hook."""


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def active_claim(
    conn: Any,
    target: WorkClaimTarget,
    *,
    for_update: bool = False,
) -> Optional[CoordinationClaim]:
    """Return the live claim on this target's exclusivity unit, if any."""
    where, params = conflict_match_clause(conn, target, alias="wc")
    suffix = (
        " FOR UPDATE OF wc"
        if for_update and db_backend.connection_is_postgres(conn)
        else ""
    )
    row = conn.execute(
        f"SELECT {SELECT_COLUMNS} {FROM_CLAUSE} "
        f"WHERE {where} AND wc.released_at IS NULL "
        f"ORDER BY wc.claimed_at DESC, wc.id DESC LIMIT 1{suffix}",
        tuple(params),
    ).fetchone()
    return row_to_claim(row) if row is not None else None


def get_claim(conn: Any, claim_id: int) -> CoordinationClaim:
    """Fetch one claim by id or raise :class:`CoordinationClaimNotFoundError`."""
    row = conn.execute(
        f"SELECT {SELECT_COLUMNS} {FROM_CLAUSE} WHERE wc.id = {_p(conn)}",
        (int(claim_id),),
    ).fetchone()
    if row is None:
        raise CoordinationClaimNotFoundError(
            f"Coordination claim id={claim_id} not found"
        )
    return row_to_claim(row)


def held_error(conn: Any, claim: CoordinationClaim) -> CoordinationClaimHeldError:
    """Build the contention-carrying error describing a live holder."""
    from yoke_core.domain.coordination_claim_contention import (
        describe_claim_contention,
    )

    contention = describe_claim_contention(conn, claim)
    error_type = (
        CoordinationClaimStaleHolderError
        if contention.holder_stale
        else CoordinationClaimHeldError
    )
    return error_type(contention.message, contention=contention)


def acquire(
    conn: Any,
    target: WorkClaimTarget,
    session_id: str,
    *,
    reason: Optional[str] = None,
    now: Optional[str] = None,
    commit: bool = True,
) -> CoordinationClaim:
    """Take the exclusive claim on ``target``.

    Conflicts surface as :class:`CoordinationClaimHeldError` carrying the
    holder's context rather than a raw integrity error.
    ``last_heartbeat`` starts at the acquisition timestamp so liveness
    reads treat a fresh claim as fully heartbeated.
    """
    now = now or iso8601_now()
    p = _p(conn)
    existing = active_claim(conn, target)
    if existing is not None:
        raise held_error(conn, existing)
    use_savepoint = db_backend.connection_is_postgres(conn)
    if use_savepoint:
        conn.execute("SAVEPOINT coordination_claim_acquire")
    try:
        cur = conn.execute(
            "INSERT INTO work_claims "
            "(session_id, target_kind, scope, claim_type, claimed_at, "
            "last_heartbeat, released_at, release_reason) "
            f"VALUES ({p}, {p}, {p}, 'exclusive', {p}, {p}, NULL, NULL) "
            "RETURNING id",
            (session_id, target.kind, target.scope_json(), now, now),
        )
    except db_backend.integrity_error_types(conn) as exc:
        if use_savepoint:
            conn.execute("ROLLBACK TO SAVEPOINT coordination_claim_acquire")
            conn.execute("RELEASE SAVEPOINT coordination_claim_acquire")
        current = active_claim(conn, target)
        if current is not None:
            raise held_error(conn, current) from exc
        # Nothing holds the target, so this was not contention. A claim row
        # is session-bound by foreign key; reporting a missing or unknown
        # holder session as "already held" would send the caller looking
        # for a lock that does not exist.
        raise
    if use_savepoint:
        conn.execute("RELEASE SAVEPOINT coordination_claim_acquire")
    claim_id = int(cur.fetchone()[0])
    from yoke_core.domain.claim_chain_state import record_claim_reason

    record_claim_reason(conn, claim_id=claim_id, reason=reason)
    if commit:
        conn.commit()
    claim = get_claim(conn, claim_id)
    emit_claim_event(
        LEASE_ACQUIRED_EVENT,
        "INFO",
        claim,
        conn=None if commit else conn,
    )
    return claim


def heartbeat(
    conn: Any,
    claim_id: int,
    *,
    now: Optional[str] = None,
    commit: bool = True,
) -> CoordinationClaim:
    """Refresh ``last_heartbeat`` on a held claim."""
    now = now or iso8601_now()
    p = _p(conn)
    claim = get_claim(conn, claim_id)
    if not claim.is_active:
        raise CoordinationClaimReleasedError(
            f"Coordination claim id={claim_id} is released "
            f"(released_at={claim.released_at}); heartbeat refused"
        )
    conn.execute(
        f"UPDATE work_claims SET last_heartbeat = {p} "
        f"WHERE id = {p} AND released_at IS NULL",
        (now, int(claim_id)),
    )
    if commit:
        conn.commit()
    refreshed = get_claim(conn, claim_id)
    emit_claim_event(
        LEASE_HEARTBEATED_EVENT, "INFO", refreshed, conn=None if commit else conn
    )
    return refreshed


def release(
    conn: Any,
    claim_id: int,
    reason: str,
    *,
    canonical_reason: str = DEFAULT_RELEASE_REASON,
    now: Optional[str] = None,
    released_by_session_id: Optional[str] = None,
    commit: bool = True,
) -> CoordinationClaim:
    """Release a held claim. Idempotent — re-releasing returns unchanged."""
    now = now or iso8601_now()
    p = _p(conn)
    claim = get_claim(conn, claim_id)
    if not claim.is_active:
        return claim
    conn.execute(
        f"UPDATE work_claims SET released_at = {p}, release_reason = {p} "
        f"WHERE id = {p} AND released_at IS NULL",
        (now, canonical_reason, int(claim_id)),
    )
    from yoke_core.domain.claim_chain_state import record_release_intent

    record_release_intent(conn, claim_id=int(claim_id), intent=reason)
    if commit:
        conn.commit()
    released = get_claim(conn, claim_id)
    emit_claim_event(
        LEASE_RELEASED_EVENT,
        "INFO",
        released,
        context={
            "release_reason": reason,
            "released_by_session_id": released_by_session_id,
        },
        conn=None if commit else conn,
    )
    return released


def emit_claim_event(
    name: str,
    severity: str,
    claim: CoordinationClaim,
    *,
    context: Optional[Dict[str, Any]] = None,
    conn: Optional[Any] = None,
) -> None:
    """Fire one coordination-claim lifecycle event, best-effort."""
    payload: Dict[str, Any] = {
        "claim_id": claim.id,
        "project_id": claim.project_id,
        "lease_key": claim.key,
        "target_kind": claim.target.kind,
        "scope": dict(claim.target.scope),
        "session_id": claim.session_id,
        "owner_item_id": claim.owner_item_id,
        "actor_id": claim.actor_id,
        "sticky": claim.sticky,
        "claimed_at": claim.claimed_at,
        "last_heartbeat": claim.last_heartbeat,
        "released_at": claim.released_at,
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
            session_id=claim.session_id,
            project=claim.project_id,
            severity=severity,
            outcome="completed",
            context=payload,
            conn=conn,
        )
    except Exception:
        # Best-effort telemetry; the claim row remains the source of truth.
        pass


__all__ = [
    "DEFAULT_RELEASE_REASON",
    "LEASE_ACQUIRED_EVENT",
    "LEASE_HEARTBEATED_EVENT",
    "LEASE_RELEASED_EVENT",
    "OPERATOR_LEASE_RELEASE_EVENT",
    "CoordinationClaim",
    "CoordinationClaimError",
    "CoordinationClaimHeldError",
    "CoordinationClaimHookContextError",
    "CoordinationClaimNotFoundError",
    "CoordinationClaimReleasedError",
    "CoordinationClaimStaleHolderError",
    "acquire",
    "active_claim",
    "emit_claim_event",
    "get_claim",
    "held_error",
    "heartbeat",
    "release",
]
