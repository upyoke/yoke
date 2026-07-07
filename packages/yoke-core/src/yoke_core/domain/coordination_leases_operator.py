"""Operator recovery for stranded coordination leases.

Sibling of :mod:`yoke_core.domain.coordination_leases`. Owns the human-only
``operator_release`` surface plus its WARN-severity ``OperatorLeaseRelease``
emission. The split keeps the core lease module lean while preserving the
ledger-first recovery property: the event lands before the release mutation
so a telemetry outage cannot mask a successful operator action.

Importable through both this module and ``coordination_leases`` (the latter
re-exports for backward compatibility).
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from yoke_core.domain.coordination_leases import (
    LeaseError,
    LeaseHookContextError,
    LeaseNotFoundError,
    OPERATOR_LEASE_RELEASE_EVENT,
    active_lease,
    release_lease,
)
from yoke_core.domain.project_identity import resolve_project_id


def operator_release(
    conn: Any,
    project_id: str | int,
    lease_key: str,
    operator_reason: str,
    *,
    session_id: Optional[str] = None,
    now: Optional[str] = None,
) -> Dict[str, Any]:
    """Human-only operator recovery for a stranded lease.

    Refuses invocation from a hook context (``YOKE_HOOK_EVENT`` set),
    emits a WARN ``OperatorLeaseRelease`` event *before* the release
    mutation lands (ledger-first), and then releases the active lease.

    Returns a summary dict describing the released lease; raises
    :class:`LeaseNotFoundError` when no live lease exists for the key.
    """
    if os.environ.get("YOKE_HOOK_EVENT"):
        raise LeaseHookContextError(
            "Operator lease-release cannot be invoked from a hook context "
            f"(YOKE_HOOK_EVENT={os.environ['YOKE_HOOK_EVENT']}). "
            "This command is human-only."
        )

    if not operator_reason or not operator_reason.strip():
        raise LeaseError("operator_reason must be a non-empty string")

    numeric_project_id = resolve_project_id(conn, project_id)
    lease = active_lease(conn, numeric_project_id, lease_key)
    if lease is None:
        raise LeaseNotFoundError(
            f"No active lease for {project_id}:{lease_key}"
        )

    effective_session = session_id or lease.session_id

    context = {
        "lease_id": lease.id,
        "project_id": numeric_project_id,
        "lease_key": lease_key,
        "prior_session_id": lease.session_id,
        "acquired_at": lease.acquired_at,
        "operator_reason": operator_reason,
        "release_reason_intent": "operator-override",
    }
    _emit_operator_lease_release(
        session_id=effective_session,
        project_id=numeric_project_id,
        context=context,
    )

    released = release_lease(
        conn,
        lease.id,
        reason=f"operator-override: {operator_reason}",
        now=now,
    )

    return {
        "released": True,
        "lease_id": released.id,
        "project_id": released.project_id,
        "lease_key": released.lease_key,
        "prior_session_id": lease.session_id,
        "operator_session_id": effective_session,
        "operator_reason": operator_reason,
        "released_at": released.released_at,
    }


def _emit_operator_lease_release(
    *,
    session_id: str,
    project_id: int,
    context: Dict[str, Any],
) -> None:
    """Fire a WARN ``OperatorLeaseRelease`` event via the shared emitter."""
    try:
        from yoke_core.domain.events import emit_event as _emit

        _emit(
            OPERATOR_LEASE_RELEASE_EVENT,
            event_kind="system",
            event_type="lease_lifecycle",
            source_type="api",
            session_id=session_id,
            project=project_id,
            severity="WARN",
            outcome="completed",
            context=context,
        )
    except Exception:
        # Best-effort telemetry; operator release proceeds so recovery is
        # not wedged by a telemetry outage.
        pass


__all__ = ["operator_release"]
