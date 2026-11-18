"""Deployment run row reads, computed membership, and requested completion diagnostics."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.deployment_common import error, run_id
from yoke_core.domain.deployment_run_driver_attachment import (
    COLUMN as DRIVER_ATTACHMENT_FIELD,
    parse_attachment,
)


def _recorded_driver(run_id_value: str) -> Optional[Dict[str, Any]]:
    """The recorded driver, live or lapsed, for a reader that judges liveness."""
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.schema_common import _column_exists

    with connect() as conn:
        if not _column_exists(conn, "deployment_runs", DRIVER_ATTACHMENT_FIELD):
            return None
        row = conn.execute(
            f"SELECT {DRIVER_ATTACHMENT_FIELD} FROM deployment_runs WHERE id=%s",
            (run_id_value,),
        ).fetchone()
    field = DRIVER_ATTACHMENT_FIELD
    raw = None if row is None else row[field] if hasattr(row, "keys") else row[0]
    attachment = parse_attachment(run_id_value, raw)
    return None if attachment is None else attachment.as_dict()


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


def _presentation_scope(request, run_id_value):
    from yoke_core.domain.actor_project_visibility import numeric_actor_id
    from yoke_core.domain.db_helpers import connect, utc_now
    from yoke_core.domain.deployment_run_driver_attachment import (
        live_attachment_for_run,
    )
    from yoke_core.domain.items_project_scope import actor_visible_scope

    if request.actor is None or numeric_actor_id(request.actor.actor_id) is None:
        return None, None, None
    with connect() as conn:
        # The live driver reads the atomic preparation receipt to recover a
        # lost response. Project readers must not receive that execution data.
        driver = live_attachment_for_run(conn, run_id_value=run_id_value, now=utc_now())
        if driver is not None and driver.session_id == request.actor.session_id:
            return None, None, None
        row = conn.execute(
            "SELECT dr.project_id,df.stages FROM deployment_runs dr "
            "JOIN deployment_flows df ON df.id=dr.flow WHERE dr.id=%s",
            (run_id_value,),
        ).fetchone()
        if row is None:
            return set(), None, None
        return actor_visible_scope(conn, request), row["project_id"], row["stages"]


def _scope_field(name, value, scope):
    from yoke_core.domain.deployment_run_project_presentation import (
        visible_bound_sources,
        visible_carried_work,
    )
    from yoke_core.domain.json_helper import dumps_compact

    visible, owner, stages = scope
    if visible is None:
        return value
    if name == "bound_sources" and value:
        return dumps_compact(
            visible_bound_sources(value, stages, visible, owner_id=owner)
        )
    if name == "carried_work":
        return visible_carried_work(value, owner, visible)
    if name in {"requirement_snapshot", "composition_resolution"}:
        return ""
    return value


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
    driver = DRIVER_ATTACHMENT_FIELD in (requested or ())
    stored = [
        name
        for name in requested or ()
        if name not in member_names and name != DRIVER_ATTACHMENT_FIELD
    ]
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
            f"{', '.join((*computed.COMPUTED_RUN_FIELDS, DRIVER_ATTACHMENT_FIELD))}.",
            jsonpath="$.payload.fields" if fields is not None else "$.payload.field",
        )
    if raw is None:
        return error(
            "not_found",
            f"deployment run '{resolved_run_id}' not found",
            jsonpath="$.target.workflow_run_id",
        )
    sensitive = {
        "bound_sources",
        "carried_work",
        "requirement_snapshot",
        "composition_resolution",
    }
    scope = (
        _presentation_scope(request, resolved_run_id)
        if requested is None
        or sensitive.intersection(requested)
        or any(name not in computed.LINEAGE_RUN_FIELDS for name in member_names)
        else (None, None, None)
    )
    values: Dict[str, Any] = (
        computed.run_membership(resolved_run_id, visible=scope[0])
        if requested is None
        or any(name not in computed.LINEAGE_RUN_FIELDS for name in member_names)
        else {}
    )
    if requested is None or any(
        name in computed.LINEAGE_RUN_FIELDS for name in requested
    ):
        values.update(computed.run_lineage(resolved_run_id))
    if driver:
        values[DRIVER_ATTACHMENT_FIELD] = _recorded_driver(resolved_run_id)
    if field:
        value = (
            values[field]
            if field in values
            else computed.carried_work_for(resolved_run_id, {"carried_work": raw})
            if field == "carried_work"
            else raw
        )
        return HandlerOutcome(
            result_payload={
                "run_id": resolved_run_id,
                "field": field,
                "value": _scope_field(field, value, scope),
            },
            primary_success=True,
        )
    if requested is None or "carried_work" in requested:
        values["carried_work"] = computed.carried_work_for(resolved_run_id, raw)
    parsed = {
        name: _scope_field(name, value, scope)
        for name, value in {**raw, **values}.items()
    }
    if fields is not None:
        run = {name: parsed[name] for name in fields}
        return HandlerOutcome(
            result_payload={"run_id": resolved_run_id, "fields": fields, "run": run},
            primary_success=True,
        )
    from yoke_core.domain.release_delivery_attestation import attestation_warnings

    diagnostics = {}
    if payload.get("include_member_closure"):
        from yoke_core.domain.deployment_run_completion_preview import (
            run_completion_diagnostics,
        )

        diagnostics["member_closure"] = run_completion_diagnostics(
            resolved_run_id,
            visible_item_ids=None
            if scope[0] is None
            else {member["id"] for member in parsed["member_items"]},
        )
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
