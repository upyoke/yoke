"""Metadata-only read of one QA artifact; never resolves evidence bytes or URLs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionCallRequest, FunctionError, HandlerOutcome


class ArtifactGetRequest(BaseModel):
    artifact_id: int


class ArtifactGetResponse(BaseModel):
    artifact: dict[str, Any]


def handle_artifact_get(request: FunctionCallRequest) -> HandlerOutcome:
    requirement_id = request.target.qa_requirement_id
    if request.target.kind != "qa_requirement" or requirement_id is None:
        return HandlerOutcome(primary_success=False, error=FunctionError(
            code="target_invalid", message="qa.artifact.get requires a QA requirement target",
        ))
    try:
        payload = ArtifactGetRequest.model_validate(request.payload or {})
    except ValueError as exc:
        return HandlerOutcome(primary_success=False, error=FunctionError(
            code="payload_invalid", message=str(exc), jsonpath="$.payload",
        ))

    from yoke_core.domain import db_backend
    from yoke_core.domain.db_helpers import connect, query_one

    with connect() as conn:
        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = query_one(
            conn,
            "SELECT a.id, a.qa_run_id, a.artifact_type, a.content_type, "
            "a.metadata, a.created_at FROM qa_artifacts a "
            "JOIN qa_runs r ON r.id=a.qa_run_id "
            f"WHERE a.id={marker} AND r.qa_requirement_id={marker}",
            (payload.artifact_id, requirement_id),
        )
    if row is None:
        return HandlerOutcome(primary_success=False, error=FunctionError(
            code="not_found", message=f"artifact {payload.artifact_id} not found for requirement {requirement_id}",
        ))
    return HandlerOutcome(primary_success=True, result_payload={"artifact": dict(row)})


__all__ = ["ArtifactGetRequest", "ArtifactGetResponse", "handle_artifact_get"]
