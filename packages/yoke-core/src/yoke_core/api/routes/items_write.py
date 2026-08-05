"""Shared-mutation routes for creating and updating work items."""

from __future__ import annotations

from typing import Any, Dict

from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter

from yoke_core.domain import db_backend
from yoke_core.domain.mutations import (
    SUPPORTED_UPDATE_FIELDS,
    GateContext,
    ItemState,
    prepare_create,
    prepare_update,
)
from yoke_core.domain.project_identity import render_item_ref, resolve_project_id
from yoke_core.api.service_client import _resolve_deploy_envs
from yoke_core.api.routes.item_delivery_binding_update import (
    lock_and_validate_delivery_binding,
    prospective_project_for_update,
)

# Module-level import so test patches against ``yoke_core.api.main.*`` take effect.
import yoke_core.api.main as _main

router = APIRouter()


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _item_read_sql(conn) -> str:
    p = _p(conn)
    return (
        "SELECT i.*, pr.slug AS project FROM items i "
        "LEFT JOIN projects pr ON pr.id = i.project_id "
        f"WHERE i.id = {p}"
    )


def _translate_project_write(conn, writes: Dict[str, Any]) -> None:
    if "project" not in writes:
        return
    project = writes.pop("project") or "yoke"
    writes["project_id"] = resolve_project_id(conn, project)


def _next_project_sequence(conn, project_id: int) -> int:
    p = _p(conn)
    row = conn.execute(
        f"SELECT COALESCE(MAX(project_sequence), 0) + 1 FROM items WHERE project_id = {p}",
        (project_id,),
    ).fetchone()
    return int(row[0])


@router.post("/items", response_model=_main.ItemObject, status_code=201)
def create_item(req: _main.CreateItemRequest) -> _main.ItemObject | JSONResponse:
    """Create a new item via the shared mutation layer.

    The route is the ``web_form`` entry surface. The selected workflow
    definition decides whether web filing is allowed.
    """
    from yoke_core.domain.deployment_flow_validator import (
        normalize_deployment_flow_value,
        validate_and_lookup_flow_project,
    )

    deployment_flow = normalize_deployment_flow_value(req.deployment_flow)
    conn = _main.get_db_readonly()
    try:
        flow_project, flow_err = validate_and_lookup_flow_project(
            conn, deployment_flow, req.project
        )
        from yoke_core.domain.workflow_registry import (
            WorkflowRegistryError,
            resolve_current_workflow_pin,
        )
        from yoke_core.domain.workflow_runtime import load_workflow_runtime

        workflow_id, workflow_version_id = resolve_current_workflow_pin(
            conn,
            req.workflow,
        )
        workflow = load_workflow_runtime(
            conn,
            workflow_id=workflow_id,
            workflow_version_id=workflow_version_id,
        )
    except WorkflowRegistryError as exc:
        return _main._error_response(
            422,
            "VALIDATION_ERROR",
            str(exc),
        )
    finally:
        conn.close()

    if flow_err:
        return _main._error_response(422, "VALIDATION_ERROR", flow_err)

    result = prepare_create(
        title=req.title,
        workflow=workflow,
        priority=req.priority,
        project=req.project,
        deployment_flow=deployment_flow,
        flow_project=flow_project,
    )

    if not result.success:
        return _main._error_response(
            422,
            result.error_code or "VALIDATION_ERROR",
            result.error or "Unknown error",
        )

    from yoke_core.domain.item_entry_surface import enforce_item_entry_allowed

    intake_block = enforce_item_entry_allowed(
        workflow=workflow,
        entry_surface="web_form",
    )
    if intake_block:
        return _main._error_response(
            403,
            "ENTRY_SURFACE_DENIED",
            intake_block,
        )

    field_writes = dict(result.field_writes)
    if field_writes.get("project") is None:
        field_writes["project"] = "yoke"

    conn = _main.get_db_readwrite()
    try:
        p = _p(conn)
        if deployment_flow:
            _locked_project, flow_err = validate_and_lookup_flow_project(
                conn,
                deployment_flow,
                req.project,
                lock_binding=True,
            )
            if flow_err:
                return _main._error_response(422, "VALIDATION_ERROR", flow_err)
        _translate_project_write(conn, field_writes)
        field_writes["project_sequence"] = _next_project_sequence(
            conn,
            int(field_writes["project_id"]),
        )
        columns = list(field_writes.keys())
        col_str = ", ".join(columns)
        values = [
            int(field_writes[c])
            if isinstance(field_writes[c], bool)
            else field_writes[c]
            for c in columns
        ]
        placeholders = ", ".join([p] * len(columns))
        cursor = conn.execute(
            f"INSERT INTO items ({col_str}) VALUES ({placeholders}) RETURNING id",
            values,
        )
        item_id = cursor.fetchone()[0]
        conn.commit()

        row = conn.execute(_item_read_sql(conn), (item_id,)).fetchone()
        if row is None:
            return _main._error_response(
                500,
                "INTERNAL_ERROR",
                f"Item {render_item_ref(conn, int(item_id))} was created "
                "but could not be read back",
            )
        return _main._row_to_item(row, include_body=True)
    except db_backend.operational_error_types(conn) as exc:
        if "database is locked" in str(exc).lower():
            return _main._error_response(
                503,
                "DB_BUSY",
                "Database is locked. Retry after a short delay.",
            )
        raise
    finally:
        conn.close()


@router.patch("/items/{item_id}", response_model=_main.ItemObject)
def update_item(
    item_id: int, req: _main.UpdateItemRequest
) -> _main.ItemObject | JSONResponse:
    """Update one or more fields on an existing item."""
    updates = {k: v for k, v in req.model_dump().items() if v is not None}

    if not updates:
        return _main._error_response(
            422,
            "VALIDATION_ERROR",
            "At least one field must be provided for update.",
        )

    unsupported = set(updates.keys()) - SUPPORTED_UPDATE_FIELDS
    if unsupported:
        return _main._error_response(
            422,
            "UNSUPPORTED_FIELD",
            f"Field(s) {', '.join(sorted(unsupported))} not in supported update surface.",
        )
    if "status" in updates:
        return _main._error_response(
            409,
            "STATUS_UPDATE_REQUIRES_LIFECYCLE",
            (
                "PATCH cannot update item status. Use the authenticated "
                "lifecycle.transition.execute function surface."
            ),
        )

    conn = _main.get_db_readwrite()
    try:
        p = _p(conn)
        row = conn.execute(_item_read_sql(conn), (item_id,)).fetchone()
        if row is None:
            return _main._error_response(
                404,
                "NOT_FOUND",
                f"Item with id {item_id} not found",
            )
        flow_project = None
        if "project" in updates or "deployment_flow" in updates:
            row, flow_project, binding_error = lock_and_validate_delivery_binding(
                conn,
                item_id=item_id,
                updates=updates,
                initial_row=row,
                read_item=lambda db, target_id: db.execute(
                    _item_read_sql(db), (target_id,)
                ).fetchone(),
            )
            if binding_error:
                return _main._error_response(422, "VALIDATION_ERROR", binding_error)
        if row is None:
            return _main._error_response(
                404,
                "NOT_FOUND",
                f"Item with id {item_id} not found",
            )

        item_dict = dict(row)
        from yoke_core.domain.workflow_runtime import (
            load_item_workflow_runtime,
        )

        workflow = load_item_workflow_runtime(conn, item_id)
        prospective_project = prospective_project_for_update(
            updates,
            item_dict,
        )
        item_state = ItemState(
            id=item_dict["id"],
            item_ref=render_item_ref(conn, int(item_dict["id"])),
            title=item_dict["title"],
            status=item_dict["status"],
            priority=item_dict["priority"],
            rework_count=item_dict.get("rework_count", 0),
            frozen=bool(item_dict.get("frozen", 0)),
            project=prospective_project,
            deployment_flow=item_dict.get("deployment_flow"),
            deploy_stage=item_dict.get("deploy_stage"),
            deployed_to=item_dict.get("deployed_to"),
            merged_at=item_dict.get("merged_at"),
            workflow=workflow,
        )

        gate = GateContext()
        if "deployment_flow" in updates and updates["deployment_flow"]:
            gate.flow_project = flow_project

        if "deployed_to" in updates and updates["deployed_to"]:
            resolved_envs = _resolve_deploy_envs(conn, prospective_project)
            gate.valid_deploy_envs = resolved_envs if resolved_envs is not None else []

        combined_writes: Dict[str, Any] = {}
        for field_name, value in updates.items():
            result = prepare_update(
                item=item_state,
                field_name=field_name,
                value=value,
                gate=gate,
            )
            if not result.success:
                return _main._error_response(
                    422
                    if result.error_code in ("VALIDATION_ERROR", "UNSUPPORTED_FIELD")
                    else 409,
                    result.error_code or "VALIDATION_ERROR",
                    result.error or "Unknown error",
                )
            combined_writes.update(result.field_writes)

        if combined_writes:
            _translate_project_write(conn, combined_writes)
            set_parts = [f"{k} = {p}" for k in combined_writes.keys()]
            # Boolean flag columns (frozen, blocked) are INTEGER; bind Python
            # bools as 0/1. SQLite adapts bool->int implicitly (byte-identical),
            # but Postgres rejects a bool bound to an integer column.
            values = [
                int(v) if isinstance(v, bool) else v for v in combined_writes.values()
            ] + [item_id]
            conn.execute(
                f"UPDATE items SET {', '.join(set_parts)} WHERE id = {p}",
                values,
            )
            conn.commit()

        row = conn.execute(_item_read_sql(conn), (item_id,)).fetchone()
        return _main._row_to_item(row, include_body=True)
    except db_backend.operational_error_types(conn) as exc:
        if "database is locked" in str(exc).lower():
            return _main._error_response(
                503,
                "DB_BUSY",
                "Database is locked. Retry after a short delay.",
            )
        raise
    finally:
        conn.close()


__all__ = ["router"]
