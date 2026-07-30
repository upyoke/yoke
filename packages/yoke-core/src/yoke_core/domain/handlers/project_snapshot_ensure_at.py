"""Handler for ``project.snapshot.ensure_at``.

Lazily ensures a path snapshot exists for ``(project, commit_sha)``,
building it server-side when absent. This is the transport-aware form of
:func:`yoke_core.domain.path_snapshots.ensure_snapshot_at`: callers that
resolve a commit SHA from their local checkout (post-merge cache pre-warm,
post-commit hooks) relay the write here so the snapshot lands on the
connected control plane — dispatched in-process against a local Postgres
connection, or over https server-side — without opening a bare local
``connect()``.

Unlike ``project.snapshot.sync``, the client sends only the SHA; the
server walks that commit's tree to build the snapshot. Idempotent against
``(project_id, commit_sha)``: an existing snapshot is returned unchanged.
It is ``adapter_status='internal'`` engine-relayed glue (never an agent CLI
surface), session-optional like its sibling sync handler.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class ProjectSnapshotEnsureAtRequest(BaseModel):
    commit_sha: str = Field(..., min_length=1)
    project: Optional[str] = None
    project_id: Optional[str] = None


class ProjectSnapshotEnsureAtResponse(BaseModel):
    project: str
    commit_sha: str
    snapshot_id: int


def _project_ref(request: FunctionCallRequest, body: ProjectSnapshotEnsureAtRequest):
    ref = request.target.project_id or body.project_id or body.project
    return None if ref is None else str(ref)


def handle_project_snapshot_ensure_at(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = ProjectSnapshotEnsureAtRequest.model_validate(request.payload or {})
    except ValidationError as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid", message=str(exc), jsonpath="$.payload"
            ),
        )
    project_ref = _project_ref(request, body)
    if not project_ref:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="project_required",
                message=(
                    "snapshot ensure_at needs a project context; pass "
                    "`project` or run from a registered checkout"
                ),
            ),
        )

    from yoke_core.domain import db_helpers
    from yoke_core.domain.path_snapshots import ensure_snapshot_at
    from yoke_core.domain.project_identity import resolve_project_id

    try:
        with db_helpers.connect() as conn:
            project_id = resolve_project_id(conn, project_ref)
            snapshot_id = ensure_snapshot_at(conn, project_id, body.commit_sha)
    except Exception as exc:  # noqa: BLE001 - advisory write; surface for the caller
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="snapshot_ensure_failed", message=str(exc)
            ),
        )

    return HandlerOutcome(
        result_payload={
            "project": str(project_id),
            "commit_sha": body.commit_sha,
            "snapshot_id": int(snapshot_id),
        },
        primary_success=True,
    )


__all__ = [
    "ProjectSnapshotEnsureAtRequest",
    "ProjectSnapshotEnsureAtResponse",
    "handle_project_snapshot_ensure_at",
]
