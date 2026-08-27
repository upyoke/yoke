"""One-shot, stage-only authority for proving a private session route."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any, Mapping

from yoke_contracts.session_control.capabilities import capability_for_surface
from yoke_contracts.session_control.private_route_qualification import (
    QUALIFICATION_ABANDONED_REASON,
    QUALIFICATION_RELEASE_REASON,
    PrivateRouteQualificationGrant,
    PrivateRouteQualificationScope,
    qualification_expires_at,
)
from yoke_contracts.session_control.surface_versions import (
    surface_operation_supported,
    surface_version_supported,
)
from yoke_core.domain import db_backend
from yoke_core.domain.coordination_claim_record import CoordinationClaim
from yoke_core.domain.work_claim_targets import (
    make_route_qualification_target,
)
from yoke_core.domain.db_helpers import iso8601_now


QUALIFICATION_ACQUIRE_REASON = "private-route-qualification"


class PrivateRouteQualificationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _runtime_release(scope: PrivateRouteQualificationScope) -> None:
    environment = str(os.environ.get("YOKE_ENVIRONMENT") or "").strip()
    build = str(os.environ.get("YOKE_BUILD_SHA") or "").strip()
    if environment != "stage":
        raise PrivateRouteQualificationError(
            "qualification_stage_only", "private-route qualification is stage-only"
        )
    if len(build) != 40 or build != scope.release_sha:
        raise PrivateRouteQualificationError(
            "qualification_release_mismatch",
            "private-route qualification requires the exact serving release",
        )


def _private_candidate(scope: PrivateRouteQualificationScope) -> None:
    capability = capability_for_surface(scope.surface)
    interface = getattr(capability, scope.operation, "none") if capability else "none"
    if interface != "private" or not surface_version_supported(
        scope.surface, scope.version
    ):
        raise PrivateRouteQualificationError(
            "qualification_scope_unsupported",
            "scope does not name a private candidate route",
        )
    if surface_operation_supported(scope.surface, scope.version, scope.operation):
        raise PrivateRouteQualificationError(
            "qualification_canonical_route",
            "canonical version evidence already authorizes this route",
        )


def _active_operator_identity(
    conn: Any,
    *,
    session_id: str,
    actor_id: str,
    project_id: int,
) -> None:
    marker = _marker(conn)
    row = conn.execute(
        "SELECT actor_id,ended_at,mode FROM harness_sessions "
        f"WHERE session_id={marker}",
        (session_id,),
    ).fetchone()
    expected_actor = str(actor_id or "")
    if (
        row is None
        or not expected_actor.isdigit()
        or str(row["actor_id"] or "") != expected_actor
        or row["ended_at"] is not None
        or str(row["mode"] or "") != "operator"
    ):
        raise PrivateRouteQualificationError(
            "qualification_owner_inactive",
            "qualification owner is not an active operator session",
        )
    from yoke_core.domain.actor_permissions import (
        PERM_PROJECT_ADMIN,
        permission_decision,
    )

    if not permission_decision(
        conn,
        actor_id=int(expected_actor),
        project_id=project_id,
        permission_key=PERM_PROJECT_ADMIN,
    ).allowed:
        raise PrivateRouteQualificationError(
            "qualification_owner_forbidden",
            "qualification owner no longer administers the project",
        )


def _active_operator(conn: Any, lease: CoordinationClaim) -> None:
    _active_operator_identity(
        conn,
        session_id=lease.session_id,
        actor_id=str(lease.actor_id or ""),
        project_id=int(lease.project_id or 0),
    )


def grant_from_lease(
    conn: Any,
    lease: CoordinationClaim,
    scope: PrivateRouteQualificationScope,
    *,
    now: datetime | None = None,
) -> PrivateRouteQualificationGrant:
    if (
        not lease.is_active
        or int(lease.project_id or 0) <= 0
        or lease.key != scope.lease_key
    ):
        raise PrivateRouteQualificationError(
            "qualification_grant_inactive", "qualification grant is not active"
        )
    _runtime_release(scope)
    _private_candidate(scope)
    _active_operator(conn, lease)
    expires_at = qualification_expires_at(lease.claimed_at)
    if (now or datetime.now(timezone.utc)) >= _utc(expires_at):
        raise PrivateRouteQualificationError(
            "qualification_grant_expired", "qualification grant has expired"
        )
    return PrivateRouteQualificationGrant(
        lease_id=lease.id,
        project_id=int(lease.project_id or 0),
        sender_session_id=lease.session_id,
        operator_actor_id=str(lease.actor_id),
        opened_at=lease.claimed_at,
        expires_at=expires_at,
        grant_digest=scope.digest,
        scope=scope,
    )


def open_qualification_grant(
    conn: Any,
    *,
    project_id: int,
    sender_session_id: str,
    operator_actor_id: int,
    scope: PrivateRouteQualificationScope,
    now: str | None = None,
) -> PrivateRouteQualificationGrant:
    _runtime_release(scope)
    _private_candidate(scope)
    _active_operator_identity(
        conn,
        session_id=sender_session_id,
        actor_id=str(operator_actor_id),
        project_id=project_id,
    )
    from yoke_core.domain.coordination_claims import (
        acquire,
        active_claim,
        release,
    )

    opened_at = now or iso8601_now()
    target = make_route_qualification_target(project_id, scope.grant_key)
    existing = active_claim(conn, target, for_update=True)
    if existing is not None and _utc(opened_at) >= _utc(
        qualification_expires_at(existing.claimed_at)
    ):
        release(
            conn,
            existing.id,
            QUALIFICATION_ABANDONED_REASON,
            canonical_reason="expired",
            now=opened_at,
            released_by_session_id=sender_session_id,
            commit=False,
        )
    try:
        lease = acquire(
            conn,
            target,
            sender_session_id,
            reason=QUALIFICATION_ACQUIRE_REASON,
            now=opened_at,
            commit=False,
        )
        grant = grant_from_lease(conn, lease, scope)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return grant


def _message_scope(
    conn: Any,
    candidate: Mapping[str, Any],
    *,
    operation: str,
    route: str,
) -> tuple[PrivateRouteQualificationScope, str] | None:
    marker = _marker(conn)
    row = conn.execute(
        "SELECT sender_session_id,idempotency_key FROM session_messages "
        f"WHERE message_id={marker}",
        (str(candidate.get("message_id") or ""),),
    ).fetchone()
    if row is None or not row["sender_session_id"]:
        return None
    key = str(row["idempotency_key"] or "")
    parts = key.split(":")
    if len(parts) < 4 or parts[0] != "fleet-live":
        return None
    run_id = parts[1]
    build = str(os.environ.get("YOKE_BUILD_SHA") or "").strip()
    try:
        scope = PrivateRouteQualificationScope(
            release_sha=build,
            acceptance_run_id=run_id,
            surface=str(candidate.get("executor_surface") or ""),
            version=str(candidate.get("executor_version") or ""),
            operation=operation,
            route=route,
        )
    except Exception:
        return None
    return scope, str(row["sender_session_id"])


def qualification_for_message(
    conn: Any,
    candidate: Mapping[str, Any],
    *,
    operation: str,
    route: str,
    now: datetime | None = None,
) -> PrivateRouteQualificationGrant | None:
    canonical = surface_operation_supported(
        str(candidate.get("executor_surface") or ""),
        str(candidate.get("executor_version") or ""),
        operation,
    )
    if canonical:
        return None
    resolved = _message_scope(conn, candidate, operation=operation, route=route)
    if resolved is None:
        return None
    scope, sender_session_id = resolved
    from yoke_core.domain.coordination_claims import active_claim

    lease = active_claim(
        conn,
        make_route_qualification_target(
            int(candidate["project_id"]), scope.grant_key
        ),
        for_update=True,
    )
    if lease is None or lease.session_id != sender_session_id:
        return None
    return grant_from_lease(conn, lease, scope, now=now)


def consume_qualification_grant(
    conn: Any,
    grant: PrivateRouteQualificationGrant,
    *,
    now: str | None = None,
) -> None:
    marker = _marker(conn)
    released_at = now or iso8601_now()
    cursor = conn.execute(
        "UPDATE work_claims SET released_at="
        + marker
        + ",release_reason='completed',release_reason_intent="
        + marker
        + f" WHERE id={marker} AND released_at IS NULL",
        (released_at, QUALIFICATION_RELEASE_REASON, grant.lease_id),
    )
    if cursor.rowcount != 1:
        raise PrivateRouteQualificationError(
            "qualification_grant_consumed", "qualification grant was already consumed"
        )


__all__ = [
    "PrivateRouteQualificationError",
    "consume_qualification_grant",
    "grant_from_lease",
    "open_qualification_grant",
    "qualification_for_message",
]
