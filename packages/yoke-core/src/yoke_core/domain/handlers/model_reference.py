"""Registered read/validate surface for the sourced model reference."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.model_reference import (
    ModelReferenceError,
    iter_model_records,
    lookup_model_reference,
    validate_model_record,
)

LOOKUP_FUNCTION_ID = "models.lookup.run"
GET_FUNCTION_ID = "models.get.run"
VALIDATE_FUNCTION_ID = "models.validate.run"


class ModelsLookupRequest(BaseModel):
    model_id: str = Field(..., min_length=1)


class ModelsGetRequest(BaseModel):
    model_id: Optional[str] = None


class ModelsValidateRequest(BaseModel):
    record: Dict[str, Any]


class ModelsLookupResponse(BaseModel):
    model_id: str
    researched: bool
    record: Optional[Dict[str, Any]] = None


class ModelsGetResponse(BaseModel):
    model_id: Optional[str] = None
    researched: Optional[bool] = None
    record: Optional[Dict[str, Any]] = None
    records: Optional[List[Dict[str, Any]]] = None
    count: Optional[int] = None


class ModelsValidateResponse(BaseModel):
    valid: bool
    record: Dict[str, Any]


def _payload_error(exc: ValidationError) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(
            code="payload_invalid",
            message=str(exc),
            recovery_hint="See `yoke models lookup --help` / `yoke models get --help` / `yoke models validate --help`.",
        ),
    )


def handle_models_lookup(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        spec = ModelsLookupRequest.model_validate(request.payload or {})
    except ValidationError as exc:
        return _payload_error(exc)
    lookup = lookup_model_reference(spec.model_id)
    return HandlerOutcome(result_payload=lookup.to_dict(), primary_success=True)


def handle_models_get(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        spec = ModelsGetRequest.model_validate(request.payload or {})
    except ValidationError as exc:
        return _payload_error(exc)
    if spec.model_id:
        lookup = lookup_model_reference(spec.model_id)
        return HandlerOutcome(result_payload=lookup.to_dict(), primary_success=True)
    records = [record.to_dict() for record in iter_model_records()]
    return HandlerOutcome(
        result_payload={"records": records, "count": len(records)},
        primary_success=True,
    )


def handle_models_validate(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        spec = ModelsValidateRequest.model_validate(request.payload or {})
    except ValidationError as exc:
        return _payload_error(exc)
    try:
        record = validate_model_record(spec.record)
    except ModelReferenceError as exc:
        return HandlerOutcome(
            result_payload={},
            primary_success=False,
            error=FunctionError(
                code=exc.code,
                message=str(exc),
                recovery_hint=(
                    "Fix the named field and retry `yoke models validate --stdin`. "
                    "Unknown leaves are null, not guesses."
                ),
            ),
        )
    return HandlerOutcome(
        result_payload={"record": record.to_dict(), "valid": True},
        primary_success=True,
    )
