"""Chunked HTTPS dispatch for project snapshot sync."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import uuid4

from yoke_cli.commands._helpers import ensure_handlers_loaded
from yoke_cli.commands.adapters.project_snapshot_chunk_sizing import (
    active_transport_is_https,
    needs_https_chunking,
    raise_if_https_chunk_payload_too_large,
    snapshot_file_chunks,
)
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)
from yoke_contracts.path_snapshot import (
    PathSnapshotPayload,
    PathSnapshotSyncPayload,
)
from yoke_contracts.path_snapshot_chunks import (
    PathSnapshotChunkMetadata,
    PathSnapshotChunkSyncPayload,
)

SNAPSHOT_CHUNK_UPLOAD_MISSING_CODE = "snapshot_chunk_upload_missing"


def dispatch_chunked_sync_payload(
    *,
    project: Optional[str],
    payload: PathSnapshotSyncPayload,
    session_id: Optional[str],
    timeout_s: Optional[float],
) -> FunctionCallResponse:
    snapshots: List[Dict[str, Any]] = []
    warnings: List[str] = []
    project_id = None
    rows_by_commit_sha: Dict[str, Dict[str, Any]] = {}
    for snapshot in payload.snapshots:
        existing_row = rows_by_commit_sha.get(snapshot.commit_sha)
        if existing_row is not None:
            snapshots.append(_alias_snapshot_row(snapshot, existing_row))
            warnings.extend(snapshot.warnings)
            continue
        response = _upload_snapshot_with_restart(
            project=project,
            repo_root=payload.repo_root,
            snapshot=snapshot,
            hook_mode=payload.hook_mode,
            session_id=session_id,
            timeout_s=timeout_s,
        )
        if not response.success:
            return response
        result = response.result or {}
        project_id = result.get("project_id", project_id)
        result_rows = result.get("snapshots") or []
        snapshots.extend(result_rows)
        warnings.extend(result.get("warnings") or [])
        for row in result_rows:
            commit_sha = row.get("commit_sha")
            if commit_sha:
                rows_by_commit_sha.setdefault(str(commit_sha), row)
    return FunctionCallResponse(
        success=True,
        function="project.snapshot.sync",
        version="v1",
        result={
            "project_id": project_id,
            "snapshots": snapshots,
            "warnings": warnings,
        },
    )


def _upload_snapshot_with_restart(**kwargs: Any) -> FunctionCallResponse:
    """Upload one snapshot, restarting once if its staging went missing.

    Server-side staging is deleted on abort and on a completed finalize, so
    a call whose response was lost finds nothing to append to or finalize on
    its retry. A restart mints a fresh upload id, which makes recovering
    from that window automatic rather than an operator errand.
    """
    response = _upload_snapshot(**kwargs)
    if _staging_went_missing(response):
        return _upload_snapshot(**kwargs)
    return response


def _staging_went_missing(response: FunctionCallResponse) -> bool:
    if response.success:
        return False
    return getattr(response.error, "code", "") == (
        SNAPSHOT_CHUNK_UPLOAD_MISSING_CODE
    )


def _upload_snapshot(
    *,
    project: Optional[str],
    repo_root: Optional[str],
    snapshot: PathSnapshotPayload,
    hook_mode: bool,
    session_id: Optional[str],
    timeout_s: Optional[float],
) -> FunctionCallResponse:
    upload_id = uuid4().hex
    chunks = snapshot_file_chunks(
        project=project,
        repo_root=repo_root,
        upload_id=upload_id,
        snapshot=snapshot,
        hook_mode=hook_mode,
    )
    begin = PathSnapshotChunkSyncPayload(
        project_id=project,
        repo_root=repo_root,
        upload_id=upload_id,
        operation="begin",
        snapshot=PathSnapshotChunkMetadata(
            ref=snapshot.ref,
            commit_sha=snapshot.commit_sha,
            file_count=len(snapshot.files),
            chunk_count=len(chunks),
            symlinks=snapshot.symlinks,
            warnings=snapshot.warnings,
        ),
        hook_mode=hook_mode,
    )
    response = dispatch_chunk_payload(
        project=project, payload=begin, session_id=session_id,
        timeout_s=timeout_s,
    )
    if not response.success:
        return response
    begin_result = response.result or {}
    reuse_row = _begin_reuse_row(snapshot, begin_result)
    if reuse_row is not None:
        return _upload_result(
            begin_result, [reuse_row], begin_result.get("warnings") or [],
        )
    if hook_mode:
        _abort(project, upload_id, session_id, timeout_s)
        return _deferral_response()
    for chunk_index, files in enumerate(chunks):
        append = PathSnapshotChunkSyncPayload(
            project_id=project,
            repo_root=repo_root,
            upload_id=upload_id,
            operation="append",
            chunk_index=chunk_index,
            files=files,
            hook_mode=hook_mode,
        )
        response = _dispatch_or_abort(
            project, upload_id, append, session_id, timeout_s,
        )
        if not response.success:
            return response
    finalize = PathSnapshotChunkSyncPayload(
        project_id=project,
        repo_root=repo_root,
        upload_id=upload_id,
        operation="finalize",
        hook_mode=hook_mode,
    )
    response = _dispatch_or_abort(
        project, upload_id, finalize, session_id, timeout_s,
    )
    if not response.success:
        return response
    result = response.result or {}
    return _upload_result(
        result, result.get("snapshots") or [], result.get("warnings") or [],
    )


def _dispatch_or_abort(
    project: Optional[str],
    upload_id: str,
    payload: PathSnapshotChunkSyncPayload,
    session_id: Optional[str],
    timeout_s: Optional[float],
) -> FunctionCallResponse:
    try:
        response = dispatch_chunk_payload(
            project=project, payload=payload, session_id=session_id,
            timeout_s=timeout_s,
        )
    except Exception:
        _abort(project, upload_id, session_id, timeout_s)
        raise
    if not response.success:
        _abort(project, upload_id, session_id, timeout_s)
    return response


def _abort(
    project: Optional[str],
    upload_id: str,
    session_id: Optional[str],
    timeout_s: Optional[float],
) -> None:
    abort_chunk_upload(
        project=project, upload_id=upload_id,
        session_id=session_id, timeout_s=timeout_s,
    )


def _upload_result(
    source: Dict[str, Any],
    rows: List[Dict[str, Any]],
    warnings: List[str],
) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True,
        function="project.snapshot.sync",
        version="v1",
        result={
            "project_id": source.get("project_id"),
            "snapshots": rows,
            "warnings": list(warnings),
        },
    )


def _deferral_response() -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function="project.snapshot.sync",
        version="v1",
        error=FunctionError(
            code="snapshot_sync_deferred",
            message=(
                "large path snapshot deferred to keep this write fast; "
                "it uploads on the next `yoke project snapshot sync` "
                "(nothing is broken)"
            ),
        ),
    )


def _begin_reuse_row(
    snapshot: PathSnapshotPayload,
    result: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if result.get("status") != "reused":
        return None
    rows = result.get("snapshots") or []
    for row in rows:
        if row.get("commit_sha") == snapshot.commit_sha:
            return {
                **row,
                "status": "reused",
                "ref": snapshot.ref,
                "commit_sha": snapshot.commit_sha,
            }
    snapshot_id = result.get("snapshot_id")
    if snapshot_id is None:
        return None
    return {
        "status": "reused",
        "snapshot_id": snapshot_id,
        "ref": snapshot.ref,
        "commit_sha": snapshot.commit_sha,
        "entry_count": 0,
        "symlink_count": 0,
    }


def _alias_snapshot_row(
    snapshot: PathSnapshotPayload,
    source_row: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "status": "reused",
        "snapshot_id": source_row.get("snapshot_id"),
        "ref": snapshot.ref,
        "commit_sha": snapshot.commit_sha,
        "entry_count": 0,
        "symlink_count": 0,
    }


def dispatch_chunk_payload(
    *,
    project: Optional[str],
    payload: PathSnapshotChunkSyncPayload,
    session_id: Optional[str],
    timeout_s: Optional[float],
) -> FunctionCallResponse:
    raise_if_https_chunk_payload_too_large(payload)
    ensure_handlers_loaded()
    return call_dispatcher(
        function_id="project.snapshot.sync",
        target=TargetRef(kind="global", project_id=project),
        payload=payload.model_dump(mode="json"),
        actor=build_actor(session_id=session_id),
        timeout_s=timeout_s,
    )


def abort_chunk_upload(
    *,
    project: Optional[str],
    upload_id: str,
    session_id: Optional[str],
    timeout_s: Optional[float],
) -> None:
    try:
        dispatch_chunk_payload(
            project=project,
            payload=PathSnapshotChunkSyncPayload(
                project_id=project,
                upload_id=upload_id,
                operation="abort",
            ),
            session_id=session_id,
            timeout_s=timeout_s,
        )
    except Exception:
        return


__all__ = [
    "SNAPSHOT_CHUNK_UPLOAD_MISSING_CODE",
    "abort_chunk_upload",
    "active_transport_is_https",
    "dispatch_chunk_payload",
    "dispatch_chunked_sync_payload",
    "needs_https_chunking",
]
