"""Handler for ``project.snapshot.sync``."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.path_snapshot import (
    SNAPSHOT_SYNC_API_PAYLOAD_LIMIT_BYTES,
    PathSnapshotSyncPayload,
    snapshot_sync_payload_size_bytes,
)
from yoke_contracts.path_snapshot_chunks import (
    PathSnapshotChunkSyncPayload,
    snapshot_chunk_payload_size_bytes,
)
from yoke_core.domain.project_snapshot_chunk_uploads import sync_chunk


class ProjectSnapshotSyncRequest(PathSnapshotSyncPayload):
    pass


class ProjectSnapshotChunkSyncRequest(PathSnapshotChunkSyncPayload):
    pass


class ProjectSnapshotSyncResponse(BaseModel):
    project_id: int
    snapshots: List[Dict[str, Any]]
    warnings: List[str]


def handle_project_snapshot_sync(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    if (request.payload or {}).get("operation") in {
        "begin", "append", "finalize", "abort",
    }:
        return _handle_chunk_sync(request)
    try:
        payload = ProjectSnapshotSyncRequest.model_validate(request.payload or {})
    except ValidationError as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=str(exc),
                jsonpath="$.payload",
            ),
        )
    size_error = _payload_size_error(payload)
    if size_error is not None:
        return HandlerOutcome(primary_success=False, error=size_error)
    project_ref = _project_ref(request, payload)
    if not project_ref:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="project_required",
                message=(
                    "project snapshot sync needs a project context; pass "
                    "`--project` or run from a registered checkout"
                ),
            ),
        )
    try:
        result = _sync(project_ref, payload)
    except Exception as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="snapshot_sync_failed",
                message=str(exc),
                recovery_hint="Repair with `yoke project snapshot sync`.",
            ),
        )
    return HandlerOutcome(result_payload=result, primary_success=True)


def _handle_chunk_sync(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        payload = ProjectSnapshotChunkSyncRequest.model_validate(
            request.payload or {}
        )
    except ValidationError as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=str(exc),
                jsonpath="$.payload",
            ),
        )
    size_error = _chunk_payload_size_error(payload)
    if size_error is not None:
        return HandlerOutcome(primary_success=False, error=size_error)
    project_ref = _project_ref(request, payload)
    if payload.operation == "begin" and not project_ref:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="project_required",
                message=(
                    "chunked project snapshot sync needs a project context; "
                    "pass `--project` or run from a registered checkout"
                ),
            ),
        )
    try:
        result = sync_chunk(project_ref, payload, _sync)
    except Exception as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="snapshot_sync_failed",
                message=str(exc),
                recovery_hint="Repair with `yoke project snapshot sync`.",
            ),
        )
    return HandlerOutcome(result_payload=result, primary_success=True)


def _payload_size_error(
    payload: ProjectSnapshotSyncRequest,
) -> Optional[FunctionError]:
    payload_size = snapshot_sync_payload_size_bytes(payload)
    if payload_size <= SNAPSHOT_SYNC_API_PAYLOAD_LIMIT_BYTES:
        return None
    return FunctionError(
        code="payload_too_large",
        message=(
            f"snapshot sync payload is {payload_size} bytes, above the "
            f"API limit of {SNAPSHOT_SYNC_API_PAYLOAD_LIMIT_BYTES} bytes"
        ),
        jsonpath="$.payload",
        recovery_hint=(
            "Retry with `yoke project snapshot sync --head-only` or split "
            "the sync into a smaller payload."
        ),
    )


def _chunk_payload_size_error(
    payload: ProjectSnapshotChunkSyncRequest,
) -> Optional[FunctionError]:
    payload_size = snapshot_chunk_payload_size_bytes(payload)
    if payload_size <= SNAPSHOT_SYNC_API_PAYLOAD_LIMIT_BYTES:
        return None
    return FunctionError(
        code="payload_too_large",
        message=(
            f"snapshot sync chunk payload is {payload_size} bytes, above "
            f"the API limit of {SNAPSHOT_SYNC_API_PAYLOAD_LIMIT_BYTES} bytes"
        ),
        jsonpath="$.payload",
        recovery_hint=(
            "Retry with a smaller chunk size or repair from a "
            "local-core/source-dev environment."
        ),
    )


def _project_ref(
    request: FunctionCallRequest,
    payload: ProjectSnapshotSyncRequest | ProjectSnapshotChunkSyncRequest,
) -> Optional[str]:
    ref = (
        request.target.project_id
        or payload.project_id
        or request.payload.get("project")
        or request.payload.get("project_id")
    )
    return None if ref is None else str(ref)


def _sync(project_ref: str, payload: PathSnapshotSyncPayload) -> Dict[str, Any]:
    from yoke_core.domain import db_helpers
    from yoke_core.domain.path_snapshot_payload_materializer import (
        materialize_snapshot_payload,
    )
    from yoke_core.domain.project_identity import resolve_project_id

    warnings: List[str] = []
    rows: List[Dict[str, Any]] = []
    with db_helpers.connect() as conn:
        project_id = resolve_project_id(conn, project_ref)
        for snapshot in payload.snapshots:
            warnings.extend(snapshot.warnings)
            result = materialize_snapshot_payload(
                conn, project_id=project_id, payload=snapshot,
            )
            rows.append({
                "status": result.status,
                "snapshot_id": result.snapshot_id,
                "ref": result.ref,
                "commit_sha": result.commit_sha,
                "entry_count": result.entry_count,
                "symlink_count": result.symlink_count,
            })
    return {
        "project_id": project_id,
        "snapshots": rows,
        "warnings": warnings,
    }


__all__ = [
    "ProjectSnapshotChunkSyncRequest",
    "ProjectSnapshotSyncRequest",
    "ProjectSnapshotSyncResponse",
    "handle_project_snapshot_sync",
]
