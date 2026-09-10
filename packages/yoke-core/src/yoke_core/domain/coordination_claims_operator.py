"""Operator recovery for a stranded shared-operation claim.

Sibling of :mod:`yoke_core.domain.coordination_claims`. Owns the
human-only ``operator_release`` surface plus its WARN-severity
``OperatorLeaseRelease`` emission. The split keeps the core module lean
while keeping authority on the durable claim mutation: the release row
records the authenticated actor and operator-supplied reason, while the
event is best-effort diagnostic telemetry.

Sticky claim kinds have no automatic reclaim by design — the resource
they name keeps operating after its session goes quiet — so this is the
only path that frees one early, and the operator's own words stay on the
row in ``release_reason_intent``.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from yoke_core.domain.auth_context import StandardAuthContext
from yoke_core.domain.coordination_claim_keys import target_for_key
from yoke_core.domain.coordination_claims import (
    OPERATOR_LEASE_RELEASE_EVENT,
    CoordinationClaimError,
    CoordinationClaimHookContextError,
    CoordinationClaimNotFoundError,
    active_claim,
    release,
)
from yoke_core.domain.project_identity import resolve_project


class CoordinationClaimChangedError(CoordinationClaimError):
    """The reviewed claim is no longer the active holder for its key."""


def operator_release(
    conn: Any,
    project_id: str | int,
    key: str,
    operator_reason: str,
    *,
    expected_claim_id: int,
    expected_holder_session_id: str,
    operator_actor_id: int,
    now: Optional[str] = None,
) -> Dict[str, Any]:
    """Human-only operator recovery for a stranded coordination claim.

    Refuses invocation from a hook context (``YOKE_HOOK_EVENT`` set),
    emits best-effort WARN ``OperatorLeaseRelease`` diagnostic telemetry,
    and records the authenticated actor and reason on the claim release.

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

    identity = resolve_project(conn, project_id)
    assert identity is not None
    numeric_project_id = identity.id
    target = target_for_key(
        key,
        project_id=numeric_project_id,
        project_slug=identity.slug,
    )
    claim = active_claim(conn, target, for_update=True)
    if claim is None:
        raise CoordinationClaimNotFoundError(
            f"No active coordination claim for {project_id}:{key}"
        )
    expected_holder = str(expected_holder_session_id or "").strip()
    if claim.id != int(expected_claim_id) or claim.session_id != expected_holder:
        raise CoordinationClaimChangedError(
            f"Coordination claim {project_id}:{key} changed after review: "
            f"current claim id={claim.id}, holder={claim.session_id!r}; "
            f"expected id={int(expected_claim_id)}, holder={expected_holder!r}. "
            "Run `yoke coordination-claim list --project P --key K "
            "--active-only --json`, review the current holder, and retry with "
            "its exact --claim-id and --holder-session-id."
        )

    if int(operator_actor_id) <= 0:
        raise CoordinationClaimError(
            "operator_actor_id must identify the authenticated human actor"
        )

    context = {
        "claim_id": claim.id,
        "project_id": numeric_project_id,
        "lease_key": key,
        "target_kind": claim.target.kind,
        "prior_session_id": claim.session_id,
        "prior_owner_item_id": claim.owner_item_id,
        "acquired_at": claim.claimed_at,
        "operator_actor_id": int(operator_actor_id),
        "operator_reason": operator_reason,
        "release_reason_intent": "operator-override",
    }
    _emit_operator_release(
        actor_id=int(operator_actor_id),
        project_id=numeric_project_id,
        context=context,
    )

    released = release(
        conn,
        claim.id,
        f"operator-override: {operator_reason}",
        now=now,
        released_by_actor_id=int(operator_actor_id),
    )

    return {
        "released": True,
        "claim_id": released.id,
        "project_id": numeric_project_id,
        "key": key,
        "prior_session_id": claim.session_id,
        "operator_actor_id": int(operator_actor_id),
        "operator_reason": operator_reason,
        "released_at": released.released_at,
    }


def _emit_operator_release(
    *,
    actor_id: int,
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
            auth_context=StandardAuthContext(actor_id=actor_id),
            project=project_id,
            severity="WARN",
            outcome="completed",
            context=context,
        )
    except Exception:
        # Best-effort telemetry; operator release proceeds so recovery is
        # not wedged by a telemetry outage.
        pass


__all__ = ["CoordinationClaimChangedError", "operator_release"]
