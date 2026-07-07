"""Item write-side route sub-router.

Owns ``POST /items`` (create) and ``PATCH /items/{item_id}`` (multi-field
update). Both routes go through the shared mutation layer and translate
mutation results into HTTP responses.
"""

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
from yoke_core.domain.ticket_intake_provenance import (
    enforce_public_create_allowed,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.api.service_client import _resolve_deploy_envs

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

    Production callers must carry ``provenance="idea"`` (mirrors the
    sanctioned-idea-intake signal threaded through the CLI and env-var
    paths); anything else is rejected with a recovery hint that names
    ``/yoke idea``. Test-isolated DB targets bypass the gate via the
    shared helper.
    """
    from yoke_core.domain.deployment_flow_validator import (
        normalize_deployment_flow_value,
        validate_and_lookup_flow_project,
    )

    try:
        intake_db = str(_main.get_db_path())
    except Exception:
        intake_db = None
    intake_block = enforce_public_create_allowed(
        provenance=req.provenance, db_path=intake_db,
    )
    if intake_block:
        return _main._error_response(403, "IDEA_INTAKE_REQUIRED", intake_block)

    deployment_flow = normalize_deployment_flow_value(req.deployment_flow)
    conn = _main.get_db_readonly()
    try:
        flow_project, flow_err = validate_and_lookup_flow_project(
            conn, deployment_flow, req.project
        )
    finally:
        conn.close()

    if flow_err:
        return _main._error_response(422, "VALIDATION_ERROR", flow_err)

    result = prepare_create(
        title=req.title,
        item_type=req.type,
        priority=req.priority,
        project=req.project,
        deployment_flow=deployment_flow,
        flow_project=flow_project,
    )

    if not result.success:
        return _main._error_response(422, result.error_code or "VALIDATION_ERROR", result.error or "Unknown error")

    field_writes = dict(result.field_writes)
    if field_writes.get("project") is None:
        field_writes["project"] = "yoke"

    conn = _main.get_db_readwrite()
    try:
        p = _p(conn)
        _translate_project_write(conn, field_writes)
        field_writes["project_sequence"] = _next_project_sequence(
            conn, int(field_writes["project_id"]),
        )
        columns = list(field_writes.keys())
        col_str = ", ".join(columns)
        values = [
            int(field_writes[c]) if isinstance(field_writes[c], bool) else field_writes[c]
            for c in columns
        ]
        placeholders = ", ".join([p] * len(columns))
        cursor = conn.execute(
            f"INSERT INTO items ({col_str}) VALUES ({placeholders}) RETURNING id",
            values,
        )
        item_id = cursor.fetchone()[0]
        conn.commit()

        row = conn.execute(
            _item_read_sql(conn), (item_id,)
        ).fetchone()
        if row is None:
            return _main._error_response(
                500, "INTERNAL_ERROR",
                f"Item YOK-{item_id} was created but could not be read back",
            )
        return _main._row_to_item(row, include_body=True)
    except db_backend.operational_error_types(conn) as exc:
        if "database is locked" in str(exc).lower():
            return _main._error_response(
                503, "DB_BUSY",
                "Database is locked. Retry after a short delay.",
            )
        raise
    finally:
        conn.close()


@router.patch("/items/{item_id}", response_model=_main.ItemObject)
def update_item(item_id: int, req: _main.UpdateItemRequest) -> _main.ItemObject | JSONResponse:
    """Update one or more fields on an existing item."""
    updates = {
        k: v for k, v in req.model_dump().items()
        if v is not None
    }

    if not updates:
        return _main._error_response(
            422, "VALIDATION_ERROR",
            "At least one field must be provided for update.",
        )

    unsupported = set(updates.keys()) - SUPPORTED_UPDATE_FIELDS
    if unsupported:
        return _main._error_response(
            422, "UNSUPPORTED_FIELD",
            f"Field(s) {', '.join(sorted(unsupported))} not in supported update surface.",
        )

    conn = _main.get_db_readwrite()
    try:
        p = _p(conn)
        row = conn.execute(_item_read_sql(conn), (item_id,)).fetchone()
        if row is None:
            return _main._error_response(
                404, "NOT_FOUND",
                f"Item with id {item_id} not found",
            )

        item_dict = dict(row)
        item_state = ItemState(
            id=item_dict["id"],
            title=item_dict["title"],
            item_type=item_dict["type"],
            status=item_dict["status"],
            priority=item_dict["priority"],
            rework_count=item_dict.get("rework_count", 0),
            frozen=bool(item_dict.get("frozen", 0)),
            project=item_dict.get("project"),
            deployment_flow=item_dict.get("deployment_flow"),
            deploy_stage=item_dict.get("deploy_stage"),
            deployed_to=item_dict.get("deployed_to"),
            worktree=item_dict.get("worktree"),
            merged_at=item_dict.get("merged_at"),
        )

        gate = GateContext()
        if "status" in updates:
            target_status = updates["status"]

            if item_dict["type"] == "epic":
                task_count_row = conn.execute(
                    f"SELECT COUNT(*) as cnt FROM epic_tasks WHERE epic_id = {p}",
                    (item_dict["id"],),
                ).fetchone()
                gate.epic_task_count = task_count_row["cnt"] if task_count_row else 0

            gate.has_merged_at = bool(item_dict.get("merged_at"))

            qa_req_row = conn.execute(
                f"SELECT COUNT(*) as cnt FROM qa_requirements WHERE item_id = {p}",
                (item_dict["id"],),
            ).fetchone()
            gate.qa_requirement_count = qa_req_row["cnt"] if qa_req_row else 0

            if gate.qa_requirement_count > 0:
                unsatisfied_val = conn.execute(
                    f"""SELECT COUNT(*) as cnt FROM qa_requirements qr
                       WHERE qr.item_id = {p} AND qr.qa_phase IN ('validation','verification')
                       AND qr.success_policy = 'blocking'
                       AND NOT EXISTS (
                           SELECT 1 FROM qa_runs qrun
                           WHERE qrun.qa_requirement_id = qr.id
                           AND qrun.verdict IN ('pass', 'waiver')
                       )""",
                    (item_dict["id"],),
                ).fetchone()
                gate.unsatisfied_verification_blocking = unsatisfied_val["cnt"] if unsatisfied_val else 0

                unsatisfied_all = conn.execute(
                    f"""SELECT COUNT(*) as cnt FROM qa_requirements qr
                       WHERE qr.item_id = {p} AND qr.success_policy = 'blocking'
                       AND NOT EXISTS (
                           SELECT 1 FROM qa_runs qrun
                           WHERE qrun.qa_requirement_id = qr.id
                           AND qrun.verdict IN ('pass', 'waiver')
                       )""",
                    (item_dict["id"],),
                ).fetchone()
                gate.unsatisfied_all_blocking = unsatisfied_all["cnt"] if unsatisfied_all else 0

        if "deployment_flow" in updates and updates["deployment_flow"]:
            from yoke_core.domain.deployment_flow_validator import (
                normalize_deployment_flow_value,
                validate_and_lookup_flow_project,
            )

            updates["deployment_flow"] = normalize_deployment_flow_value(
                updates["deployment_flow"]
            )
            flow_project, flow_err = validate_and_lookup_flow_project(
                conn, updates["deployment_flow"], item_dict.get("project")
            )
            if flow_err:
                return _main._error_response(422, "VALIDATION_ERROR", flow_err)
            gate.flow_project = flow_project

        if "deployed_to" in updates and updates["deployed_to"]:
            project = item_dict.get("project") or "yoke"
            resolved_envs = _resolve_deploy_envs(conn, project)
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
                    422 if result.error_code in ("VALIDATION_ERROR", "UNSUPPORTED_FIELD") else 409,
                    result.error_code or "VALIDATION_ERROR",
                    result.error or "Unknown error",
                )
            combined_writes.update(result.field_writes)

        # Capture pre-write status so we can emit ItemStatusChanged once
        # after commit if the PATCH actually transitions status. The route
        # bypasses ``backlog.execute_update`` (which would otherwise own
        # the emit), so the route owns the emit itself.
        prior_status = str(item_dict.get("status") or "")

        if combined_writes:
            _translate_project_write(conn, combined_writes)
            set_parts = [f"{k} = {p}" for k in combined_writes.keys()]
            # Boolean flag columns (frozen, blocked) are INTEGER; bind Python
            # bools as 0/1. SQLite adapts bool->int implicitly (byte-identical),
            # but Postgres rejects a bool bound to an integer column.
            values = [
                int(v) if isinstance(v, bool) else v
                for v in combined_writes.values()
            ] + [item_id]
            conn.execute(
                f"UPDATE items SET {', '.join(set_parts)} WHERE id = {p}",
                values,
            )
            conn.commit()

        new_status = combined_writes.get("status")
        if new_status and prior_status and prior_status != new_status:
            from yoke_core.domain.item_status_transitions import (
                record_and_emit_item_status_change,
            )
            record_and_emit_item_status_change(
                conn,
                item_id=item_id,
                from_status=prior_status,
                to_status=new_status,
                source="items-patch",
            )

        row = conn.execute(
            _item_read_sql(conn), (item_id,)
        ).fetchone()
        return _main._row_to_item(row, include_body=True)
    except db_backend.operational_error_types(conn) as exc:
        if "database is locked" in str(exc).lower():
            return _main._error_response(
                503, "DB_BUSY",
                "Database is locked. Retry after a short delay.",
            )
        raise
    finally:
        conn.close()


__all__ = ["router"]
