"""Handlers for the remaining ``workflow_item.epic_task.*`` shapes.

Four function ids:

- ``workflow_item.epic_task.body_get`` — read a task body verbatim.
- ``workflow_item.epic_task.update_status`` — non-pipeline status write
  (terminal success statuses stay pipeline-owned and are refused).
- ``workflow_item.epic_task.simulation_upsert`` — persist a Simulator
  report as ``qa_requirements`` + ``qa_runs`` rows (epic-level target;
  no ``task_num``).
- ``workflow_item.epic_task.submission_receipt_get`` — read + validate
  the latest Engineer submission receipt from ``epic_progress_notes``.

Each handler wraps the existing domain owners on
:mod:`yoke_core.domain.epic` (``task_get_body`` /
``task_update_status`` / ``simulation_upsert`` /
``submission_receipt_get``) — business rules live there. The receipt
read returns the same ``PASS|epic|task|note|commit|ts|fields`` line the
retained ``db_router epic submission-receipt-get`` fallback prints.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from yoke_core.domain import epic
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


_OWNER_MODULE = "yoke_core.domain.handlers.workflow_item_epic_task_state"


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class BodyGetRequest(BaseModel):
    """No payload — the target carries ``(epic_id, task_num)``."""


class BodyGetResponse(BaseModel):
    epic_id: int
    task_num: int
    body: str


class UpdateStatusRequest(BaseModel):
    status: str = Field(..., min_length=1)


class UpdateStatusResponse(BaseModel):
    epic_id: int
    task_num: int
    status: str
    message: str


class SimulationUpsertRequest(BaseModel):
    phase: str = Field(..., min_length=1)
    body: str


class SimulationUpsertResponse(BaseModel):
    epic_id: int
    phase: str
    message: str


class SubmissionReceiptGetRequest(BaseModel):
    after_note_count: int = Field(0, ge=0)


class SubmissionReceiptGetResponse(BaseModel):
    epic_id: int
    task_num: int
    receipt: str


# ---------------------------------------------------------------------------
# Shared helpers (per-module by convention: tests patch
# ``<module>._open_connection`` per handler module)
# ---------------------------------------------------------------------------


def _bad_request(message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={}, primary_success=False,
        error=FunctionError(code="invalid_payload", message=message),
    )


def _not_found(message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={}, primary_success=False,
        error=FunctionError(code="target_not_found", message=message),
    )


def _open_connection():
    from yoke_core.domain import db_helpers
    return db_helpers.connect()


def _task_target(request: FunctionCallRequest) -> Optional[Tuple[int, int]]:
    target = request.target
    if (
        target.kind != "epic_task"
        or target.epic_id is None
        or target.task_num is None
    ):
        return None
    return int(target.epic_id), int(target.task_num)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def handle_body_get(request: FunctionCallRequest) -> HandlerOutcome:
    """Read one task body via ``epic.task_get_body``."""
    ids = _task_target(request)
    if ids is None:
        return _bad_request("target must carry epic_id + task_num")
    epic_id, task_num = ids
    try:
        BodyGetRequest.model_validate(request.payload)
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")
    with _open_connection() as conn:
        try:
            body = epic.task_get_body(conn, str(epic_id), task_num)
        except LookupError as exc:
            return _not_found(str(exc))
    response = BodyGetResponse(epic_id=epic_id, task_num=task_num, body=body)
    return HandlerOutcome(result_payload=response.model_dump(), primary_success=True)


def handle_update_status(request: FunctionCallRequest) -> HandlerOutcome:
    """Write a non-terminal task status via ``epic.task_update_status``.

    Runs the non-pipeline path: lifecycle-vocabulary validation plus the
    GitHub label sync side effect. Terminal success statuses raise
    ``PermissionError`` in the domain layer (pipeline-owned) and map to
    ``error.code="pipeline_required"`` here.
    """
    ids = _task_target(request)
    if ids is None:
        return _bad_request("target must carry epic_id + task_num")
    epic_id, task_num = ids
    try:
        payload = UpdateStatusRequest.model_validate(request.payload)
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")
    with _open_connection() as conn:
        try:
            message = epic.task_update_status(
                conn, str(epic_id), task_num, payload.status,
            )
        except LookupError as exc:
            return _not_found(str(exc))
        except ValueError as exc:
            return _bad_request(str(exc))
        except PermissionError as exc:
            return HandlerOutcome(
                result_payload={}, primary_success=False,
                error=FunctionError(code="pipeline_required", message=str(exc)),
            )
    response = UpdateStatusResponse(
        epic_id=epic_id, task_num=task_num,
        status=payload.status, message=message,
    )
    return HandlerOutcome(result_payload=response.model_dump(), primary_success=True)


def handle_simulation_upsert(request: FunctionCallRequest) -> HandlerOutcome:
    """Persist a simulation report via ``epic.simulation_upsert``.

    Epic-level operation: the target carries ``epic_id`` only (any
    ``task_num`` is ignored), matching the domain owner's shape.
    """
    target = request.target
    if target.kind != "epic_task" or target.epic_id is None:
        return _bad_request("target must carry epic_id")
    epic_id = int(target.epic_id)
    try:
        payload = SimulationUpsertRequest.model_validate(request.payload)
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")
    with _open_connection() as conn:
        try:
            message = epic.simulation_upsert(
                conn, str(epic_id), payload.phase, payload.body,
            )
        except RuntimeError as exc:
            return HandlerOutcome(
                result_payload={}, primary_success=False,
                error=FunctionError(code="downstream_failure", message=str(exc)),
            )
    response = SimulationUpsertResponse(
        epic_id=epic_id, phase=payload.phase, message=message,
    )
    return HandlerOutcome(result_payload=response.model_dump(), primary_success=True)


def handle_submission_receipt_get(request: FunctionCallRequest) -> HandlerOutcome:
    """Read the latest valid submission receipt via ``epic.submission_receipt_get``.

    ``LookupError`` (no receipt block after the note watermark) maps to
    ``target_not_found``; ``ValueError`` (receipt present but missing or
    failing required fields) maps to ``receipt_invalid`` so callers can
    distinguish "not submitted" from "submitted but failing".
    """
    ids = _task_target(request)
    if ids is None:
        return _bad_request("target must carry epic_id + task_num")
    epic_id, task_num = ids
    try:
        payload = SubmissionReceiptGetRequest.model_validate(request.payload)
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")
    with _open_connection() as conn:
        try:
            receipt = epic.submission_receipt_get(
                conn, str(epic_id), task_num,
                after_note_count=payload.after_note_count,
            )
        except LookupError as exc:
            return _not_found(str(exc))
        except ValueError as exc:
            return HandlerOutcome(
                result_payload={}, primary_success=False,
                error=FunctionError(code="receipt_invalid", message=str(exc)),
            )
    response = SubmissionReceiptGetResponse(
        epic_id=epic_id, task_num=task_num, receipt=receipt,
    )
    return HandlerOutcome(result_payload=response.model_dump(), primary_success=True)


# ---------------------------------------------------------------------------
# Registration descriptors
# ---------------------------------------------------------------------------


def _kwargs(
    fid: str, h: Any, req: Any, resp: Any,
    side_effects: List[str], claim: Optional[str],
) -> Dict[str, Any]:
    return {
        "function_id": fid, "handler": h,
        "request_model": req, "response_model": resp,
        "stability": "stable",
        "owner_module": _OWNER_MODULE,
        "target_kinds": ["epic_task"],
        "side_effects": side_effects,
        "emitted_event_names": ["YokeFunctionCalled"],
        "guardrails": [],
        "adapter_status": "live",
        "claim_required_kind": claim,
    }


REGISTRATIONS: List[Dict[str, Any]] = [
    _kwargs(
        "workflow_item.epic_task.body_get", handle_body_get,
        BodyGetRequest, BodyGetResponse, [], None,
    ),
    _kwargs(
        "workflow_item.epic_task.update_status", handle_update_status,
        UpdateStatusRequest, UpdateStatusResponse,
        ["epic_tasks_status_update", "github_sync"], "epic",
    ),
    _kwargs(
        "workflow_item.epic_task.simulation_upsert", handle_simulation_upsert,
        SimulationUpsertRequest, SimulationUpsertResponse,
        ["qa_requirements_insert", "qa_runs_insert"], "epic",
    ),
    _kwargs(
        "workflow_item.epic_task.submission_receipt_get",
        handle_submission_receipt_get,
        SubmissionReceiptGetRequest, SubmissionReceiptGetResponse, [], None,
    ),
]


__all__ = [
    "handle_body_get", "handle_update_status",
    "handle_simulation_upsert", "handle_submission_receipt_get",
    "BodyGetRequest", "BodyGetResponse",
    "UpdateStatusRequest", "UpdateStatusResponse",
    "SimulationUpsertRequest", "SimulationUpsertResponse",
    "SubmissionReceiptGetRequest", "SubmissionReceiptGetResponse",
    "REGISTRATIONS",
]
