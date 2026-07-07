"""``PathClaimOverride`` event emission helper.

Sibling of :mod:`yoke_core.domain.path_claims_events` because that
module is at its line-budget cap. Owns the operator-collision-
approval emission contract:

* Severity ``WARN`` — overrides are normal failure-mode reactions
  surfaced to operators, not silent telemetry.
* Outcome ``completed`` because the override action did happen; the
  *blocked* state belongs to the underlying ``PathClaimRegistration
  Blocked`` / ``PathClaimAmendmentBlocked`` events that this override
  is permitting past.
* Payload fields ():

  ============================  =============================================
  ``path_claim_id``             claim being allowed to proceed
  ``override_point``            ``creation`` | ``amend`` |
                                ``revalidation_conflict``
  ``conflict_reason``           required for ``revalidation_conflict``;
                                ``upstream_delete`` / ``hostile_upstream_touch``
                                / ``claim_overlap`` / ``continuity_unknown``
  ``blocking_claim_id``         the other claim, when applicable
  ``blocking_path_targets``     anchor roots of the collision, NOT a full
                                descendant enumeration
  ``integration_target``        coordination universe (usually ``main``)
  ``actor_id``                  accountable actor invoking the override
  ``actor_reason``              required non-empty free-text reason
  ``invoked_at``                ISO timestamp
  ============================  =============================================

The event is telemetry alongside the ``path_claim_overrides`` state
row. The companion :mod:`yoke_core.domain.path_claims_override`
module owns the row insert and reads the table to answer "is this
claim pair currently overridden?" — gating never scans the ledger.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from yoke_core.domain import path_claims_events as _base_events


_VALID_OVERRIDE_POINTS = ("creation", "amend", "revalidation_conflict")
_VALID_CONFLICT_REASONS = (
    "upstream_delete",
    "hostile_upstream_touch",
    "claim_overlap",
    "continuity_unknown",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit_override(
    *,
    conn: Any,
    path_claim_id: int,
    override_point: str,
    integration_target: str,
    actor_id: int,
    actor_reason: str,
    blocking_claim_id: Optional[int] = None,
    blocking_path_targets: Optional[List[int]] = None,
    conflict_reason: Optional[str] = None,
    invoked_at: Optional[str] = None,
    item_id: Optional[int] = None,
    project: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Optional[str]:
    """Emit ``PathClaimOverride`` (WARN, lifecycle).

    Returns the event id on success or ``None`` when the underlying
    emit helper is unavailable. Validates inputs eagerly so the
    payload shape stays canonical.
    """
    if override_point not in _VALID_OVERRIDE_POINTS:
        raise ValueError(
            f"override_point must be one of {_VALID_OVERRIDE_POINTS!r}, "
            f"got {override_point!r}"
        )
    if (
        override_point == "revalidation_conflict"
        and not (conflict_reason or "").strip()
    ):
        raise ValueError(
            "conflict_reason is required when override_point="
            "'revalidation_conflict'"
        )
    if conflict_reason and conflict_reason not in _VALID_CONFLICT_REASONS:
        raise ValueError(
            f"conflict_reason must be one of {_VALID_CONFLICT_REASONS!r}, "
            f"got {conflict_reason!r}"
        )
    if not (actor_reason or "").strip():
        raise ValueError(
            "actor_reason is required and must be non-empty"
        )

    context: Dict[str, Any] = {
        "path_claim_id": int(path_claim_id),
        "override_point": override_point,
        "integration_target": integration_target,
        "actor_id": int(actor_id),
        "actor_reason": actor_reason,
        "invoked_at": invoked_at or _now_iso(),
        "blocking_path_targets": list(blocking_path_targets or []),
    }
    if blocking_claim_id is not None:
        context["blocking_claim_id"] = int(blocking_claim_id)
    if conflict_reason:
        context["conflict_reason"] = conflict_reason

    return _base_events._emit(
        name="PathClaimOverride",
        severity="WARN",
        outcome="completed",
        conn=conn,
        item_id=item_id,
        project=project,
        session_id=session_id,
        context=context,
    )


__all__ = [
    "emit_override",
    "_VALID_OVERRIDE_POINTS",
    "_VALID_CONFLICT_REASONS",
]
