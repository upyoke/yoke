"""Internal server-side evaluators for the advance implementation-entry gates.

The pre-worktree refusal gates the advance implementation-entry runs before
an item advances into ``implementing`` read the control-plane DB: upstream
hard-block dependencies, acceptance-criteria presence, the effective File
Budget requirement, and File-Budget-vs-claim spec coverage. Each gate used
to open a local ``connect()`` directly, so over an https control plane —
where there is no local Postgres — the evaluation failed.

These handlers are thin wrappers over the existing gate domain functions
(:mod:`yoke_core.domain.check_hard_blocks`,
:mod:`yoke_core.domain.check_ac_presence`,
:mod:`yoke_core.domain.file_budget_required_gate`,
:mod:`yoke_core.domain.path_claim_spec_coverage_gate`), unchanged. The
transport-aware preflight relays to them so the DB reads run server-side
over https and dispatch in-process against local Postgres. They are
``adapter_status='internal'`` (pure preflight glue, never an agent CLI
surface), so they carry no CLI adapter inventory row.

The narrative construction and gate ordering stay client-side in
:mod:`yoke_core.engines.advance_implementation_preflight_gates`; these
handlers return only the raw gate verdicts.
"""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class HardBlocksEvalRequest(BaseModel):
    item_id: Optional[int] = None
    gate_filter: str = "activation"


class HardBlocksEvalResponse(BaseModel):
    blockers: List[str] = Field(default_factory=list)


class AcPresenceEvalRequest(BaseModel):
    item_id: Optional[int] = None


class AcPresenceEvalResponse(BaseModel):
    canonical: int
    unlabeled: int
    title: Optional[str] = None


class FileBudgetEvalRequest(BaseModel):
    item_id: Optional[int] = None


class FileBudgetEvalResponse(BaseModel):
    verdict: str
    reason: str


class SpecCoverageEvalRequest(BaseModel):
    item_id: Optional[int] = None


class SpecCoverageEvalResponse(BaseModel):
    is_blocked: bool
    missing_paths: List[str] = Field(default_factory=list)


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _connect_rw() -> Any:
    from yoke_core.domain import db_helpers
    return db_helpers.connect()


def _resolved_item_id(
    request: FunctionCallRequest, payload_item_id: object
) -> int:
    if payload_item_id is not None:
        return int(payload_item_id)
    if request.target.item_id is not None:
        return int(request.target.item_id)
    raise ValueError("resolved item target required")


def handle_hard_blocks(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = HardBlocksEvalRequest.model_validate(request.payload)
        item_id = _resolved_item_id(request, body.item_id)
    except Exception as exc:
        return _err("payload_invalid", f"hard_blocks payload invalid: {exc}")

    from yoke_core.domain.check_hard_blocks import evaluate_blockers

    blockers = evaluate_blockers(item_id, gate_filter=body.gate_filter)
    return HandlerOutcome(
        result_payload={"blockers": list(blockers)},
        primary_success=True,
    )


def handle_ac_presence(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = AcPresenceEvalRequest.model_validate(request.payload)
        item_id = _resolved_item_id(request, body.item_id)
    except Exception as exc:
        return _err("payload_invalid", f"ac_presence payload invalid: {exc}")

    from yoke_core.domain.check_ac_presence import evaluate_item

    canonical, unlabeled, title = evaluate_item(item_id)
    return HandlerOutcome(
        result_payload={
            "canonical": int(canonical),
            "unlabeled": int(unlabeled),
            "title": title,
        },
        primary_success=True,
    )


def handle_file_budget(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = FileBudgetEvalRequest.model_validate(request.payload)
        item_id = _resolved_item_id(request, body.item_id)
    except Exception as exc:
        return _err("payload_invalid", f"file_budget payload invalid: {exc}")

    from yoke_core.domain.file_budget_required_gate import evaluate

    with _connect_rw() as conn:
        result = evaluate(conn, item_id)
    return HandlerOutcome(
        result_payload={
            "verdict": str(result["verdict"]),
            "reason": str(result["reason"]),
        },
        primary_success=True,
    )


def handle_spec_coverage(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = SpecCoverageEvalRequest.model_validate(request.payload)
        item_id = _resolved_item_id(request, body.item_id)
    except Exception as exc:
        return _err("payload_invalid", f"spec_coverage payload invalid: {exc}")

    from yoke_core.domain.path_claim_spec_coverage_gate import evaluate

    with _connect_rw() as conn:
        result = evaluate(item_id, conn=conn)
    return HandlerOutcome(
        result_payload={
            "is_blocked": bool(result.is_blocked),
            "missing_paths": list(result.missing_paths),
        },
        primary_success=True,
    )


__all__ = [
    "HardBlocksEvalRequest",
    "HardBlocksEvalResponse",
    "AcPresenceEvalRequest",
    "AcPresenceEvalResponse",
    "FileBudgetEvalRequest",
    "FileBudgetEvalResponse",
    "SpecCoverageEvalRequest",
    "SpecCoverageEvalResponse",
    "handle_hard_blocks",
    "handle_ac_presence",
    "handle_file_budget",
    "handle_spec_coverage",
]
