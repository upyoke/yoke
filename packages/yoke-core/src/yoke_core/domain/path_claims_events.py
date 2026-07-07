"""Event emission helpers for the path-claim lifecycle and gates.

Covers the required path-claim event names. Each helper wraps the canonical
:func:`yoke_core.domain.events.emit_event` so consumers (the
on-ramp surface, the amend surface, the lifecycle dispatcher's
release/cancel commands, the boundary check) emit decision-shaped,
ledgered events without re-authoring the envelope shape.

Required event names:

  PathClaimRegistered            (INFO, lifecycle)
  PathClaimActivated             (INFO, lifecycle)
  PathClaimAmended               (INFO, lifecycle)
  PathClaimReleased              (INFO, lifecycle)
  PathClaimCancelled             (INFO, lifecycle)
  PathClaimActivationBlocked     (WARN, lifecycle)
  PathClaimRegistrationBlocked   (WARN, lifecycle)
  PathClaimAmendmentBlocked      (WARN, lifecycle)
  PathClaimBoundaryCheckPassed   (INFO, lifecycle)
  PathClaimBoundaryCheckBlocked  (WARN, lifecycle)

Decision-shaped payloads only — no per-file activity logs.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional


_EVENT_KIND = "lifecycle"
_EVENT_TYPE = "path_claim"
_SOURCE_TYPE = "system"


def _resolve_session_id(explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    for env_name in (
        "YOKE_SESSION_ID", "CLAUDE_SESSION_ID", "CODEX_THREAD_ID",
    ):
        value = os.environ.get(env_name)
        if value:
            return value
    return ""


def _emit(
    *,
    name: str,
    severity: str,
    outcome: str,
    conn: Optional[Any],
    item_id: Optional[int],
    project: Optional[str],
    session_id: Optional[str],
    context: Dict[str, Any],
) -> Optional[str]:
    """Best-effort emit; return event id or ``None`` on failure."""
    try:
        from yoke_core.domain.events import emit_event as _native_emit
    except ImportError:
        return None
    try:
        envelope = _native_emit(
            name,
            event_kind=_EVENT_KIND,
            event_type=_EVENT_TYPE,
            source_type=_SOURCE_TYPE,
            session_id=_resolve_session_id(session_id),
            severity=severity,
            outcome=outcome,
            project=project or "yoke",
            item_id=item_id,
            context=context,
            conn=conn,
        )
    except Exception:
        return None
    if envelope is None:
        return None
    return envelope.get("event_id")


def emit_registered(
    *, conn, claim: Dict[str, Any], project: Optional[str] = None,
) -> Optional[str]:
    return _emit(
        name="PathClaimRegistered",
        severity="INFO",
        outcome="completed",
        conn=conn,
        item_id=claim.get("item_id"),
        project=project,
        session_id=claim.get("session_id"),
        context={
            "claim_id": claim.get("id"),
            "state": claim.get("state"),
            "mode": claim.get("mode"),
            "integration_target": claim.get("integration_target"),
            "actor_id": claim.get("actor_id"),
            "target_ids": list(claim.get("target_ids") or []),
            "blocked_reason": claim.get("blocked_reason"),
            "exception_reason": claim.get("exception_reason"),
        },
    )


def emit_registration_blocked(
    *,
    conn,
    item_id: Optional[int],
    integration_target: Optional[str],
    reason: str,
    blocking_claim_id: Optional[int] = None,
    project: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Optional[str]:
    return _emit(
        name="PathClaimRegistrationBlocked",
        severity="WARN",
        outcome="blocked",
        conn=conn,
        item_id=item_id,
        project=project,
        session_id=session_id,
        context={
            "integration_target": integration_target,
            "reason": reason,
            "blocking_claim_id": blocking_claim_id,
        },
    )


def emit_activated(
    *, conn, claim: Dict[str, Any], project: Optional[str] = None,
) -> Optional[str]:
    return _emit(
        name="PathClaimActivated",
        severity="INFO",
        outcome="completed",
        conn=conn,
        item_id=claim.get("item_id"),
        project=project,
        session_id=claim.get("session_id"),
        context={
            "claim_id": claim.get("id"),
            "integration_target": claim.get("integration_target"),
            "base_commit_sha": claim.get("base_commit_sha"),
            "actor_id": claim.get("actor_id"),
        },
    )


def emit_activation_blocked(
    *,
    conn,
    claim_id: int,
    integration_target: Optional[str],
    reason: str,
    blocking_claim_id: Optional[int] = None,
    item_id: Optional[int] = None,
    project: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Optional[str]:
    return _emit(
        name="PathClaimActivationBlocked",
        severity="WARN",
        outcome="blocked",
        conn=conn,
        item_id=item_id,
        project=project,
        session_id=session_id,
        context={
            "claim_id": claim_id,
            "integration_target": integration_target,
            "reason": reason,
            "blocking_claim_id": blocking_claim_id,
        },
    )


def emit_amended(
    *,
    conn,
    claim: Dict[str, Any],
    amendment_id: int,
    amendment_kind: str,
    payload: Dict[str, Any],
    reason: str,
    project: Optional[str] = None,
) -> Optional[str]:
    return _emit(
        name="PathClaimAmended",
        severity="INFO",
        outcome="completed",
        conn=conn,
        item_id=claim.get("item_id"),
        project=project,
        session_id=claim.get("session_id"),
        context={
            "claim_id": claim.get("id"),
            "amendment_id": amendment_id,
            "amendment_kind": amendment_kind,
            "payload": payload,
            "reason": reason,
        },
    )


def emit_amendment_blocked(
    *,
    conn,
    claim_id: int,
    amendment_kind: str,
    reason: str,
    offending_target_ids: Optional[list] = None,
    blocking_claim_id: Optional[int] = None,
    item_id: Optional[int] = None,
    project: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Optional[str]:
    return _emit(
        name="PathClaimAmendmentBlocked",
        severity="WARN",
        outcome="blocked",
        conn=conn,
        item_id=item_id,
        project=project,
        session_id=session_id,
        context={
            "claim_id": claim_id,
            "amendment_kind": amendment_kind,
            "reason": reason,
            "offending_target_ids": list(offending_target_ids or []),
            "blocking_claim_id": blocking_claim_id,
        },
    )


def emit_released(
    *, conn, claim: Dict[str, Any], reason: str,
    project: Optional[str] = None,
) -> Optional[str]:
    return _emit(
        name="PathClaimReleased",
        severity="INFO",
        outcome="completed",
        conn=conn,
        item_id=claim.get("item_id"),
        project=project,
        session_id=claim.get("session_id"),
        context={
            "claim_id": claim.get("id"),
            "integration_target": claim.get("integration_target"),
            "release_reason": reason,
        },
    )


def emit_cancelled(
    *, conn, claim: Dict[str, Any], reason: str,
    project: Optional[str] = None,
) -> Optional[str]:
    return _emit(
        name="PathClaimCancelled",
        severity="INFO",
        outcome="completed",
        conn=conn,
        item_id=claim.get("item_id"),
        project=project,
        session_id=claim.get("session_id"),
        context={
            "claim_id": claim.get("id"),
            "integration_target": claim.get("integration_target"),
            "cancel_reason": reason,
        },
    )


def emit_boundary_passed(
    *,
    conn,
    claim_id: int,
    integration_target: str,
    status: str,
    item_id: Optional[int] = None,
    project: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Optional[str]:
    return _emit(
        name="PathClaimBoundaryCheckPassed",
        severity="INFO",
        outcome="completed",
        conn=conn,
        item_id=item_id,
        project=project,
        session_id=session_id,
        context={
            "claim_id": claim_id,
            "integration_target": integration_target,
            "boundary_status": status,
        },
    )


def emit_boundary_blocked(
    *,
    conn,
    claim_id: int,
    integration_target: str,
    diagnostics: str,
    offending_target_ids: Optional[list] = None,
    item_id: Optional[int] = None,
    project: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Optional[str]:
    return _emit(
        name="PathClaimBoundaryCheckBlocked",
        severity="WARN",
        outcome="blocked",
        conn=conn,
        item_id=item_id,
        project=project,
        session_id=session_id,
        context={
            "claim_id": claim_id,
            "integration_target": integration_target,
            "diagnostics": diagnostics,
            "offending_target_ids": list(offending_target_ids or []),
        },
    )


__all__ = [
    "emit_activated",
    "emit_activation_blocked",
    "emit_amended",
    "emit_amendment_blocked",
    "emit_boundary_blocked",
    "emit_boundary_passed",
    "emit_cancelled",
    "emit_registered",
    "emit_registration_blocked",
    "emit_released",
]
