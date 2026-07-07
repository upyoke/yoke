"""Shared charge-invariant cleanup for session-offer CLI and HTTP surfaces.

When ``validate_charge_claim_invariant`` refuses a CHARGE directive after
an offer-time work claim has been acquired, the response left the claim
held on the aborted session — a normal ``session-end`` then refused the
session with ``ACTIVE_CLAIM`` because no chainable directive had been
emitted. The cleanup helper here closes both halves of that gap:

1. Releases the exact offer-time ``new_claim`` (when one exists) with
   reason ``offer-invariant-failed`` so the aborted session does not
   carry a stranded claim.
2. Emits the structured ``SessionOfferInvariantFailed`` event so the
   mismatch is queryable from the events table instead of grepping
   generic harness tool output.

Both shapes of invariant failure are covered:

- Mismatched ``selected_item`` vs ``new_claim.item_id`` — release the
  exact offer-time claim and emit the event.
- ``charge`` action without ``new_claim`` — emit the event with null
  claim fields and do not attempt a release.

The containment guard remains strict: callers refuse to emit a
mismatched charge directive regardless of cleanup outcome.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from yoke_core.domain.session_contract import NextAction
from yoke_core.domain.session_offer_invariant_events import (
    emit_session_offer_invariant_failed,
)
from yoke_core.domain.sessions_lifecycle_release import (
    release_item_claim_for_execution,
)
from yoke_core.api.service_client_sessions_offer_helpers import (
    validate_charge_claim_invariant,
)

OFFER_INVARIANT_FAILED_REASON = "offer-invariant-failed"

CLI_SURFACE = "cli"
HTTP_SURFACE = "http"


def _release_offer_time_claim(
    conn: Any,
    *,
    session_id: str,
    new_claim: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Release the offer-time claim if and only if a real numeric item id exists.

    Returns the release-result dict (including failure shapes from
    ``release_item_claim_for_execution``) so the caller can carry it into
    the event payload. Returns ``None`` when there is nothing to release —
    the second invariant-failure shape (charge without ``new_claim``)
    deliberately does not attempt a release.
    """
    if not new_claim:
        return None
    claim_item_id = new_claim.get("item_id")
    if claim_item_id is None:
        return None
    try:
        return release_item_claim_for_execution(
            conn,
            session_id,
            str(claim_item_id),
            OFFER_INVARIANT_FAILED_REASON,
        )
    except Exception as exc:  # noqa: BLE001 — release failure is non-fatal
        return {"released": False, "failure_reason": "release_raised", "error": str(exc)}


def handle_charge_invariant(
    conn: Any,
    *,
    session_id: str,
    result: NextAction,
    new_claim: Optional[Dict[str, Any]],
    ownership: Optional[Dict[str, Any]],
    surface: str,
    project: str = "yoke",
) -> Tuple[bool, Optional[str]]:
    """Validate the charge claim invariant; on failure release + emit.

    Returns ``(True, None)`` when the invariant holds (callers proceed
    with normal post-decision side effects). Returns ``(False, error)``
    when the guard refuses: the cleanup helper has already released the
    offer-time claim (if any) and emitted the structured event, and the
    caller surfaces ``error`` exactly the same way the previous bare
    ``validate_charge_claim_invariant`` failure path did.
    """
    ok, err = validate_charge_claim_invariant(result, new_claim)
    if ok:
        return True, None

    release_outcome = _release_offer_time_claim(
        conn,
        session_id=session_id,
        new_claim=new_claim,
    )

    emit_session_offer_invariant_failed(
        session_id=session_id,
        result=result,
        new_claim=new_claim,
        ownership=ownership,
        invariant_message=err or "",
        surface=surface,
        release_outcome=release_outcome,
        project=project,
    )
    return False, err


__all__ = [
    "CLI_SURFACE",
    "HTTP_SURFACE",
    "OFFER_INVARIANT_FAILED_REASON",
    "handle_charge_invariant",
]
