"""Deployment run row reads and explicitly requested completion diagnostics."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.deployment_common import error, run_id


class DeploymentRunGetRequest(BaseModel):
    include_member_closure: bool = False
    field: Optional[str] = None
    run_id: Optional[str] = None


class DeploymentRunGetResponse(BaseModel):
    member_closure: Optional[Dict[str, Any]] = None
    run_id: str
    field: Optional[str] = None
    value: Optional[str] = None
    fields: Optional[List[str]] = None
    run: Optional[Dict[str, Any]] = None
    attestation_warnings: Optional[List[Dict[str, str]]] = None


def handle_deployment_run_get(request: FunctionCallRequest) -> HandlerOutcome:
    resolved_run_id = run_id(request, "deployment_runs.get")
    if isinstance(resolved_run_id, HandlerOutcome):
        return resolved_run_id
    payload = request.payload or {}
    field = payload.get("field")
    if field is not None and not isinstance(field, str):
        return error(
            "payload_invalid",
            "field must be a string when present",
            jsonpath="$.payload.field",
        )

    from yoke_core.domain.deployment_runs_crud_query import cmd_get, get_run
    from yoke_core.domain.deployment_runs_schema import RUN_FIELDS

    try:
        raw = (
            cmd_get(resolved_run_id, field=field) if field else get_run(resolved_run_id)
        )
    except ValueError as exc:
        return error("invalid_field", str(exc), jsonpath="$.payload.field")
    if raw is None:
        return error(
            "not_found",
            f"deployment run '{resolved_run_id}' not found",
            jsonpath="$.target.workflow_run_id",
        )
    if field:
        return HandlerOutcome(
            result_payload={
                "run_id": resolved_run_id,
                "field": field,
                "value": raw,
            },
            primary_success=True,
        )
    parsed = raw
    from yoke_core.domain.deployment_run_carried_work import parse_carried_work
    from yoke_core.domain.release_delivery_attestation import attestation_warnings

    parsed["carried_work"] = parse_carried_work(parsed.get("carried_work"))
    diagnostics = {}
    if payload.get("include_member_closure"):
        from yoke_core.domain.deployment_run_completion_preview import (
            run_completion_diagnostics,
        )

        diagnostics["member_closure"] = run_completion_diagnostics(resolved_run_id)
    return HandlerOutcome(
        result_payload={
            "run_id": resolved_run_id,
            "fields": list(RUN_FIELDS),
            "run": parsed,
            "attestation_warnings": attestation_warnings(parsed.get("carried_work")),
            **diagnostics,
        },
        primary_success=True,
    )
