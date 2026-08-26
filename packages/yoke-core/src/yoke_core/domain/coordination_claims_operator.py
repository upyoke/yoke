"""Operator recovery for a stranded shared-operation claim.

Sibling of :mod:`yoke_core.domain.coordination_claims`. Owns the
human-only ``operator_release`` surface plus its WARN-severity
``OperatorLeaseRelease`` emission. The split keeps the core module lean
while preserving the ledger-first recovery property: the event lands
before the release mutation so a telemetry outage cannot mask a
successful operator action.

Sticky claim kinds have no automatic reclaim by design — the resource
they name keeps operating after its session goes quiet — so this is the
only path that frees one early, and the operator's own words stay on the
row in ``release_reason_intent``.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from yoke_core.domain.coordination_claim_keys import target_for_key
from yoke_core.domain.coordination_claims import (
    OPERATOR_LEASE_RELEASE_EVENT,
    CoordinationClaimError,
    CoordinationClaimHookContextError,
    CoordinationClaimNotFoundError,
    active_claim,
    release,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.session_ambient_identity import resolve_ambient_session_id


def operator_release(
    conn: Any,
    project_id: str | int,
    key: str,
    operator_reason: str,
    *,
    session_id: Optional[str] = None,
    now: Optional[str] = None,
) -> Dict[str, Any]:
    """Human-only operator recovery for a stranded coordination claim.

    Refuses invocation from a hook context (``YOKE_HOOK_EVENT`` set),
    emits a WARN ``OperatorLeaseRelease`` event *before* the release
    mutation lands (ledger-first), and then releases the live claim.

    Returns a summary dict describing the released claim; raises
    :class:`CoordinationClaimNotFoundError` when no live claim exists.
    """
    if os.environ.get("YOKE_HOOK_EVENT"):
        raise CoordinationClaimHookContextError(
            "Operator claim-release cannot be invoked from a hook context "
            f"(YOKE_HOOK_EVENT={os.environ['YOKE_HOOK_EVENT']}). "
            "This command is human-only."
        )

    if not operator_reason or not operator_reason.strip():
        raise CoordinationClaimError("operator_reason must be a non-empty string")

    numeric_project_id = resolve_project_id(conn, project_id)
    target = target_for_key(key, project_id=numeric_project_id)
    claim = active_claim(conn, target, for_update=True)
    if claim is None:
        raise CoordinationClaimNotFoundError(
            f"No active coordination claim for {project_id}:{key}"
        )

    effective_session = (session_id or resolve_ambient_session_id() or "").strip()
    if not effective_session:
        raise CoordinationClaimError(
            "operator session is required; refusing to copy the claim holder"
        )

    context = {
        "claim_id": claim.id,
        "project_id": numeric_project_id,
        "lease_key": key,
        "target_kind": claim.target.kind,
        "prior_session_id": claim.session_id,
        "prior_owner_item_id": claim.owner_item_id,
        "acquired_at": claim.claimed_at,
        "operator_reason": operator_reason,
        "release_reason_intent": "operator-override",
    }
    _emit_operator_release(
        session_id=effective_session,
        project_id=numeric_project_id,
        context=context,
    )

    released = release(
        conn,
        claim.id,
        f"operator-override: {operator_reason}",
        now=now,
        released_by_session_id=effective_session,
    )

    return {
        "released": True,
        "claim_id": released.id,
        "project_id": numeric_project_id,
        "key": key,
        "prior_session_id": claim.session_id,
        "operator_session_id": effective_session,
        "operator_reason": operator_reason,
        "released_at": released.released_at,
    }


def _emit_operator_release(
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
