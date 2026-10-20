"""Deployment run row reads, computed membership, and requested completion diagnostics."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.deployment_common import error, run_id


class DeploymentRunGetRequest(BaseModel):
    include_member_closure: bool = False
    field: Optional[str] = None
    fields: Optional[List[str]] = None
    run_id: Optional[str] = None


class DeploymentRunGetResponse(BaseModel):
    member_closure: Optional[Dict[str, Any]] = None
    run_id: str
    field: Optional[str] = None
    value: Optional[Any] = None
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

    fields = payload.get("fields")
    if fields is not None and (
        not isinstance(fields, list)
        or not fields
        or any(not isinstance(name, str) or not name for name in fields)
        or field is not None
        or payload.get("include_member_closure")
    ):
        return error(
            "payload_invalid",
            "fields must be a nonempty list of row field names; remove field and include_member_closure",
            jsonpath="$.payload.fields",
        )
    if fields is not None:
        fields = list(dict.fromkeys(fields))

    from yoke_core.domain import deployment_run_get_members as computed
    from yoke_core.domain.deployment_runs_crud_query import cmd_get, get_run
    from yoke_core.domain.deployment_runs_schema import RUN_FIELDS

    requested = fields if fields is not None else [field] if field else None
    member_names = [
        name for name in requested or () if name in computed.COMPUTED_RUN_FIELDS
    ]
    stored = [name for name in requested or () if name not in member_names]
    try:
        raw = (
            get_run(resolved_run_id)
            if requested is None
            else cmd_get(resolved_run_id, field=field)
            if field and stored
            else get_run(resolved_run_id, fields=stored or ["id"])
        )
    except ValueError as exc:
        return error(
            "invalid_field",
            f"{str(exc).rstrip('.')}. Computed fields: "
            f"{', '.join(computed.COMPUTED_RUN_FIELDS)}.",
            jsonpath="$.payload.fields" if fields is not None else "$.payload.field",
        )
    if raw is None:
        return error(
            "not_found",
            f"deployment run '{resolved_run_id}' not found",
            jsonpath="$.target.workflow_run_id",
        )
    values: Dict[str, Any] = (
        computed.run_membership(resolved_run_id)
        if requested is None or member_names
        else {}
    )
    if field:
        value = (
            values[field]
            if field in values
            else computed.carried_work_for(resolved_run_id, {"carried_work": raw})
            if field == "carried_work"
            else raw
        )
        return HandlerOutcome(
            result_payload={"run_id": resolved_run_id, "field": field, "value": value},
            primary_success=True,
        )
    if requested is None or "carried_work" in requested:
        values["carried_work"] = computed.carried_work_for(resolved_run_id, raw)
    if fields is not None:
        run = {name: values[name] if name in values else raw[name] for name in fields}
        return HandlerOutcome(
            result_payload={"run_id": resolved_run_id, "fields": fields, "run": run},
            primary_success=True,
        )
    parsed = {**raw, **values}
    from yoke_core.domain.release_delivery_attestation import attestation_warnings

    diagnostics = {}
    if payload.get("include_member_closure"):
        from yoke_core.domain.deployment_run_completion_preview import (
            run_completion_diagnostics,
        )

        diagnostics["member_closure"] = run_completion_diagnostics(resolved_run_id)
    return HandlerOutcome(
        result_payload={
            "run_id": resolved_run_id,
            "fields": [*RUN_FIELDS, *computed.COMPUTED_RUN_FIELDS],
            "run": parsed,
            "attestation_warnings": attestation_warnings(parsed.get("carried_work")),
            **diagnostics,
        },
        primary_success=True,
    )
