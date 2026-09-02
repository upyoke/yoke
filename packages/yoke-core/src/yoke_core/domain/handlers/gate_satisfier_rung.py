"""Server-side resolution and stamping of one gate's satisfier ladder.

Ladder resolution is control-plane authority: the declared capability
rows, the converged derived facts, and the durable rung stamp all live
there. Only the ``observed:`` facts belong to the caller — whether a ref
resolves in *this* worktree, whether *this* merge ran — so the caller
probes those and sends them, and everything else is read and written on
the server. That keeps one implementation of the mechanism for both
transports instead of one for a local Postgres connection and a quietly
different one for an https control plane.

The handler returns success for both outcomes and puts the verdict in
``satisfied``. A gate must block on a refusal AND on a relay failure, so
collapsing the two into one error channel would only invite a caller to
treat "the ladder says no" as recoverable. Refusals come back with the
full narrative in ``refusal`` for the gate to print verbatim.
"""

from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class ObservedFact(BaseModel):
    """One fact only the calling site could see."""

    present: bool
    detail: str = ""


class GateSatisfierResolveRequest(BaseModel):
    obligation: str = Field(..., min_length=1)
    observed: Dict[str, ObservedFact] = Field(default_factory=dict)
    target_status: str = ""


class GateSatisfierResolveResponse(BaseModel):
    obligation: str
    satisfied: bool
    rung_id: str = ""
    detail: str = ""
    refusal: str = ""
    facts: Dict[str, str] = Field(default_factory=dict)
    stamp_recorded: bool = False


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _connect_rw() -> Any:
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def handle_resolve(request: FunctionCallRequest) -> HandlerOutcome:
    """Resolve one obligation's ladder for one item and record the outcome."""
    from yoke_core.domain.gate_satisfier_resolution import (
        DerivedFactsNotConverged,
        ItemResolutionTargetMissing,
        ResolutionOnlyObligation,
        UnknownGateObligation,
        resolve_and_record_item_rung,
    )

    if request.target.item_id is None:
        return _err(
            "target_invalid", "gate_satisfier.rung.resolve requires target.item_id"
        )
    item_id = int(request.target.item_id)
    try:
        payload = GateSatisfierResolveRequest.model_validate(request.payload or {})
    except Exception as exc:  # noqa: BLE001 - normalize validation shape
        return _err("payload_invalid", str(exc))

    observed = {
        key: (fact.present, fact.detail) for key, fact in payload.observed.items()
    }
    try:
        with _connect_rw() as conn:
            result = resolve_and_record_item_rung(
                conn,
                item_id=item_id,
                obligation=payload.obligation,
                observed=observed,
                target_status=payload.target_status,
            )
    except UnknownGateObligation as exc:
        return _err("obligation_unknown", str(exc))
    except ItemResolutionTargetMissing as exc:
        return _err("item_not_found", str(exc))
    except ResolutionOnlyObligation as exc:
        return _err("obligation_resolution_only", str(exc))
    except DerivedFactsNotConverged as exc:
        return _err("derived_facts_not_converged", str(exc))
    except Exception as exc:  # noqa: BLE001 - surfaced so the gate aborts
        return _err("gate_satisfier_resolve_failed", str(exc))

    return HandlerOutcome(result_payload=result, primary_success=True)


__all__ = [
    "GateSatisfierResolveRequest",
    "GateSatisfierResolveResponse",
    "ObservedFact",
    "handle_resolve",
]
