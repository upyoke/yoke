"""Inventory immutable workflow versions without guessing a version number."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class WorkflowVersionListRequest(BaseModel):
    workflow_id: Optional[str] = None


class WorkflowVersionListResponse(BaseModel):
    rows: List[Dict[str, Any]]


def handle_workflows_version_list(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    if request.target.kind != "global":
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="target_invalid",
                message="workflows.version.list requires target.kind='global'",
                jsonpath="$.target.kind",
            ),
        )
    payload = WorkflowVersionListRequest.model_validate(request.payload or {})

    from yoke_core.domain import db_backend
    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        where = f"WHERE w.id = {marker}" if payload.workflow_id else ""
        params = (payload.workflow_id,) if payload.workflow_id else ()
        cursor = conn.execute(
            "SELECT w.id, w.name, w.status, v.version, v.id, "
            "v.definition_digest, v.published_at, "
            "CASE WHEN w.current_version_id = v.id THEN 1 ELSE 0 END "
            "FROM workflows w JOIN workflow_versions v ON v.workflow_id = w.id "
            f"{where} ORDER BY w.id, v.version",
            params,
        )
        rows = [
            {
                "workflow_id": str(row[0]),
                "name": str(row[1]),
                "status": str(row[2]),
                "version": int(row[3]),
                "version_id": int(row[4]),
                "definition_digest": str(row[5]),
                "published_at": str(row[6]),
                "current": bool(row[7]),
            }
            for row in cursor.fetchall()
        ]
    return HandlerOutcome(result_payload={"rows": rows}, primary_success=True)


__all__ = [
    "WorkflowVersionListRequest",
    "WorkflowVersionListResponse",
    "handle_workflows_version_list",
]
