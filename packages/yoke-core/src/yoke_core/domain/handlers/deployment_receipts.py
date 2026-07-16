"""Explicit read-only handlers for archived deployment receipts."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.deployment_common import error, require_global


class DeploymentFlowReceiptGetRequest(BaseModel):
    flow_id: str


class DeploymentFlowReceiptGetResponse(BaseModel):
    flow_id: str
    receipt: Dict[str, Any]


class DeploymentFlowReceiptListRequest(BaseModel):
    project: Optional[str] = None


class DeploymentFlowReceiptListResponse(BaseModel):
    fields: List[str]
    rows: List[Dict[str, Any]]


class DeploymentRunReceiptGetRequest(BaseModel):
    run_id: str


class DeploymentRunReceiptGetResponse(BaseModel):
    run_id: str
    receipt: Dict[str, Any]


class DeploymentRunReceiptListRequest(BaseModel):
    project: Optional[str] = None
    flow: Optional[str] = None
    status: Optional[str] = None


class DeploymentRunReceiptListResponse(BaseModel):
    fields: List[str]
    rows: List[Dict[str, Any]]


def _required_id(
    request: FunctionCallRequest,
    key: str,
    function_id: str,
) -> str | HandlerOutcome:
    value = (request.payload or {}).get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return error(
        "payload_invalid",
        f"{function_id} requires payload.{key}",
        jsonpath=f"$.payload.{key}",
    )


def _integrity_error(exc: Exception) -> HandlerOutcome:
    return error("receipt_invalid", str(exc))


def handle_flow_receipt_get(request: FunctionCallRequest) -> HandlerOutcome:
    invalid = require_global(request, "deployment_flow_receipts.get")
    if invalid is not None:
        return invalid
    flow_id = _required_id(request, "flow_id", "deployment_flow_receipts.get")
    if isinstance(flow_id, HandlerOutcome):
        return flow_id
    from yoke_core.domain import deployment_receipts
    try:
        receipt = deployment_receipts.get_flow_receipt(flow_id)
    except deployment_receipts.DeploymentReceiptIntegrityError as exc:
        return _integrity_error(exc)
    if receipt is None:
        return error("not_found", f"deployment flow receipt '{flow_id}' not found")
    return HandlerOutcome(
        result_payload={"flow_id": flow_id, "receipt": receipt},
        primary_success=True,
    )


def handle_flow_receipt_list(request: FunctionCallRequest) -> HandlerOutcome:
    invalid = require_global(request, "deployment_flow_receipts.list")
    if invalid is not None:
        return invalid
    project = (request.payload or {}).get("project")
    if project is not None and not isinstance(project, str):
        return error("payload_invalid", "project must be a string")
    from yoke_core.domain import deployment_receipts
    try:
        rows = deployment_receipts.list_flow_receipts(project=project)
    except deployment_receipts.DeploymentReceiptIntegrityError as exc:
        return _integrity_error(exc)
    return HandlerOutcome(
        result_payload={
            "fields": list(deployment_receipts.FLOW_LIST_FIELDS),
            "rows": rows,
        },
        primary_success=True,
    )


def handle_run_receipt_get(request: FunctionCallRequest) -> HandlerOutcome:
    invalid = require_global(request, "deployment_run_receipts.get")
    if invalid is not None:
        return invalid
    run_id = _required_id(request, "run_id", "deployment_run_receipts.get")
    if isinstance(run_id, HandlerOutcome):
        return run_id
    from yoke_core.domain import deployment_receipts
    try:
        receipt = deployment_receipts.get_run_receipt(run_id)
    except deployment_receipts.DeploymentReceiptIntegrityError as exc:
        return _integrity_error(exc)
    if receipt is None:
        return error("not_found", f"deployment run receipt '{run_id}' not found")
    return HandlerOutcome(
        result_payload={"run_id": run_id, "receipt": receipt},
        primary_success=True,
    )


def handle_run_receipt_list(request: FunctionCallRequest) -> HandlerOutcome:
    invalid = require_global(request, "deployment_run_receipts.list")
    if invalid is not None:
        return invalid
    payload = request.payload or {}
    filters: dict[str, Optional[str]] = {}
    for key in ("project", "flow", "status"):
        value = payload.get(key)
        if value is not None and not isinstance(value, str):
            return error("payload_invalid", f"{key} must be a string")
        filters[key] = value
    from yoke_core.domain import deployment_receipts
    try:
        rows = deployment_receipts.list_run_receipts(**filters)
    except deployment_receipts.DeploymentReceiptIntegrityError as exc:
        return _integrity_error(exc)
    return HandlerOutcome(
        result_payload={
            "fields": list(deployment_receipts.RUN_LIST_FIELDS),
            "rows": rows,
        },
        primary_success=True,
    )


__all__ = [
    "DeploymentFlowReceiptGetRequest",
    "DeploymentFlowReceiptGetResponse",
    "DeploymentFlowReceiptListRequest",
    "DeploymentFlowReceiptListResponse",
    "DeploymentRunReceiptGetRequest",
    "DeploymentRunReceiptGetResponse",
    "DeploymentRunReceiptListRequest",
    "DeploymentRunReceiptListResponse",
    "handle_flow_receipt_get",
    "handle_flow_receipt_list",
    "handle_run_receipt_get",
    "handle_run_receipt_list",
]
