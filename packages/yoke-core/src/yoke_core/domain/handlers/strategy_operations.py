"""Handlers for strategy operational helper surfaces."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.strategize_carry_schema import (
    DEFAULT_CARRY_LIMIT,
    DEFAULT_HORIZON_DAYS,
)


class StrategyCarryBaseRequest(BaseModel):
    project: str
    horizon_days: int = DEFAULT_HORIZON_DAYS
    carry_limit: int = DEFAULT_CARRY_LIMIT
    now: Optional[str] = None


class StrategyCarryRegisterNewResponse(BaseModel):
    project: str
    new_ids: List[int]


class StrategyCarryCandidateSetRequest(StrategyCarryBaseRequest):
    new_ids: List[int] = Field(default_factory=list)


class StrategyCarryCandidateSetResponse(BaseModel):
    candidate_set: Dict[str, Any]


class StrategyCarrySummaryRequest(StrategyCarryCandidateSetRequest):
    display_limit: int = 10


class StrategyCarrySummaryResponse(BaseModel):
    summary: str


class StrategyCarryMarkRequest(BaseModel):
    project: str
    state: str
    reason: Optional[str] = None
    items: List[str]
    now: Optional[str] = None


class StrategyCarryMarkResponse(BaseModel):
    changed: int
    state: str
    project: str


class StrategyCheckpointRequest(BaseModel):
    project: str
    kind: str = "strategize"


class StrategyCheckpointRecordResponse(BaseModel):
    recorded: bool
    project: str
    kind: str


class StrategyCheckpointLatestResponse(BaseModel):
    latest: Optional[str]
    project: str


def _bad_request(message: str, *, jsonpath: str = "$.payload") -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(
            code="payload_invalid",
            message=message,
            jsonpath=jsonpath,
        ),
    )


def _parse_item_ids(raw: List[str]) -> List[int]:
    from yoke_core.domain.strategize_carry_cli import _parse_item_ids

    return _parse_item_ids(raw)


def handle_strategy_carry_register_new(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        payload = StrategyCarryBaseRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.strategize_carry_state import register_new_landings

    with connect() as conn:
        new_ids = register_new_landings(
            conn,
            project=payload.project,
            horizon_days=payload.horizon_days,
            now_iso=payload.now,
        )
    return HandlerOutcome(
        result_payload=StrategyCarryRegisterNewResponse(
            project=payload.project,
            new_ids=new_ids,
        ).model_dump(),
        primary_success=True,
    )


def handle_strategy_carry_candidate_set(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        payload = StrategyCarryCandidateSetRequest.model_validate(
            request.payload or {}
        )
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.strategize_carry_state import get_candidate_set

    with connect() as conn:
        candidate_set = get_candidate_set(
            conn,
            project=payload.project,
            horizon_days=payload.horizon_days,
            carry_limit=payload.carry_limit,
            now_iso=payload.now,
            new_ids=payload.new_ids,
        )
    return HandlerOutcome(
        result_payload=StrategyCarryCandidateSetResponse(
            candidate_set=candidate_set,
        ).model_dump(),
        primary_success=True,
    )


def handle_strategy_carry_summary(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        payload = StrategyCarrySummaryRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.strategize_carry_state import get_candidate_set
    from yoke_core.domain.strategize_carry_summary import format_summary

    new_ids = list(payload.new_ids)
    with connect() as conn:
        candidate_set = get_candidate_set(
            conn,
            project=payload.project,
            horizon_days=payload.horizon_days,
            carry_limit=payload.carry_limit,
            now_iso=payload.now,
            new_ids=new_ids,
        )
    return HandlerOutcome(
        result_payload=StrategyCarrySummaryResponse(
            summary=format_summary(
                candidate_set,
                display_limit=payload.display_limit,
            ),
        ).model_dump(),
        primary_success=True,
    )


def handle_strategy_carry_mark(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        payload = StrategyCarryMarkRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")
    item_ids = _parse_item_ids(payload.items)
    if not item_ids:
        return _bad_request("items must contain at least one valid item id")
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.strategize_carry_state import mark_items

    with connect() as conn:
        changed = mark_items(
            conn,
            project=payload.project,
            item_ids=item_ids,
            state=payload.state,
            session_id=request.actor.session_id or None,
            reason=payload.reason,
            now_iso=payload.now,
        )
    return HandlerOutcome(
        result_payload=StrategyCarryMarkResponse(
            changed=changed,
            state=payload.state,
            project=payload.project,
        ).model_dump(),
        primary_success=True,
    )


def handle_strategy_checkpoint_record(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        payload = StrategyCheckpointRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.strategy_checkpoints import record_checkpoint

    with connect() as conn:
        recorded = record_checkpoint(conn, project=payload.project, kind=payload.kind)
        if recorded:
            conn.commit()
    if not recorded:
        return _bad_request(
            f"checkpoint not recorded (project={payload.project!r}, "
            f"kind={payload.kind!r})"
        )
    return HandlerOutcome(
        result_payload=StrategyCheckpointRecordResponse(
            recorded=True,
            project=payload.project,
            kind=payload.kind,
        ).model_dump(),
        primary_success=True,
    )


def handle_strategy_checkpoint_latest(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        payload = StrategyCheckpointRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.strategy_checkpoints import latest_checkpoint_at

    with connect() as conn:
        latest = latest_checkpoint_at(conn, payload.project)
    return HandlerOutcome(
        result_payload=StrategyCheckpointLatestResponse(
            latest=latest,
            project=payload.project,
        ).model_dump(),
        primary_success=True,
    )


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "strategy.carry.register_new",
        "handler": handle_strategy_carry_register_new,
        "request_model": StrategyCarryBaseRequest,
        "response_model": StrategyCarryRegisterNewResponse,
    },
    {
        "function_id": "strategy.carry.candidate_set",
        "handler": handle_strategy_carry_candidate_set,
        "request_model": StrategyCarryCandidateSetRequest,
        "response_model": StrategyCarryCandidateSetResponse,
    },
    {
        "function_id": "strategy.carry.summary",
        "handler": handle_strategy_carry_summary,
        "request_model": StrategyCarrySummaryRequest,
        "response_model": StrategyCarrySummaryResponse,
    },
    {
        "function_id": "strategy.carry.mark",
        "handler": handle_strategy_carry_mark,
        "request_model": StrategyCarryMarkRequest,
        "response_model": StrategyCarryMarkResponse,
    },
    {
        "function_id": "strategy.checkpoint.record",
        "handler": handle_strategy_checkpoint_record,
        "request_model": StrategyCheckpointRequest,
        "response_model": StrategyCheckpointRecordResponse,
    },
    {
        "function_id": "strategy.checkpoint.latest",
        "handler": handle_strategy_checkpoint_latest,
        "request_model": StrategyCheckpointRequest,
        "response_model": StrategyCheckpointLatestResponse,
    },
]

for entry in REGISTRATIONS:
    entry.update(
        {
            "stability": "stable",
            "owner_module": "yoke_core.domain.handlers.strategy_operations",
            "target_kinds": ["global"],
            "side_effects": ["db_write"]
            if entry["function_id"] in {
                "strategy.carry.register_new",
                "strategy.carry.mark",
                "strategy.checkpoint.record",
            }
            else [],
            "emitted_event_names": ["YokeFunctionCalled"],
            "guardrails": [],
            "adapter_status": "live",
            "claim_required_kind": None,
        }
    )


__all__ = [
    "REGISTRATIONS",
    "handle_strategy_carry_register_new",
    "handle_strategy_carry_candidate_set",
    "handle_strategy_carry_summary",
    "handle_strategy_carry_mark",
    "handle_strategy_checkpoint_record",
    "handle_strategy_checkpoint_latest",
]
