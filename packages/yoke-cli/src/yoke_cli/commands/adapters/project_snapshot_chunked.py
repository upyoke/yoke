"""Chunked dispatch for project snapshot sync: begin, append, finalize."""

from __future__ import annotations

from typing import Any, List, Optional

from yoke_cli.commands._helpers import ensure_handlers_loaded
from yoke_cli.commands.adapters.project_snapshot_chunk_results import (
    deferral_response,
)
from yoke_cli.commands.adapters.project_snapshot_chunk_sizing import (
    raise_if_https_chunk_payload_too_large,
    snapshot_file_chunks,
)
from yoke_cli.project_snapshot.sync_refs import SyncRef
from yoke_cli.project_snapshot.tree_delta import SnapshotUpload
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
from yoke_contracts.api.function_call import FunctionCallResponse, TargetRef
from yoke_contracts.path_snapshot_chunks import (
    SNAPSHOT_CHUNK_UPLOAD_MISSING_CODE,
    PathSnapshotChunkMetadata,
    PathSnapshotChunkSyncPayload,
)


# Finalize materializes contents and refreshes changed-HEAD context (up to 39s
# observed); the short hook write budget only covers staging operations.
FINALIZE_RESPONSE_TIMEOUT_S = 60.0


def offer_begin(
    *,
    project: Optional[str],
    repo_root: Optional[str],
    upload_id: str,
    ref: SyncRef,
    base_candidates: List[str],
    contents_included: bool,
    hook_mode: bool,
    session_id: Optional[str],
    timeout_s: Optional[float],
) -> FunctionCallResponse:
    """Open ``ref``'s upload before scanning any file.

    The server settles it at once when it already holds the commit (or the
    upload is identity-only), and otherwise names the first of
    ``base_candidates`` it holds a snapshot for in ``base_commit_sha``.
    """
    begin = PathSnapshotChunkSyncPayload(
        project_id=project,
        repo_root=repo_root,
        upload_id=upload_id,
        operation="begin",
        snapshot=PathSnapshotChunkMetadata(
            ref=ref.label,
            commit_sha=ref.commit_sha,
            file_count=0,
            chunk_count=0,
            warnings=ref.warnings,
            contents_included=contents_included,
            base_candidates=base_candidates,
        ),
        hook_mode=hook_mode,
    )
    return dispatch_chunk_payload(
        project=project, payload=begin, session_id=session_id, timeout_s=timeout_s
    )


def upload_snapshot(
    *,
    project: Optional[str],
    repo_root: Optional[str],
    upload_id: str,
    upload: SnapshotUpload,
    defer_multi_chunk: bool,
    hook_mode: bool,
    session_id: Optional[str],
    timeout_s: Optional[float],
) -> FunctionCallResponse:
    """Stage ``upload`` in chunks and finalize it into a stored snapshot.

    Server-side staging is deleted on abort and on a completed finalize, so
    a call whose response was lost finds nothing on its retry; that window
    restarts once under a fresh upload id instead of becoming an errand.
    """
    common = dict(
        project=project,
        repo_root=repo_root,
        upload=upload,
        defer_multi_chunk=defer_multi_chunk,
        hook_mode=hook_mode,
        session_id=session_id,
        timeout_s=timeout_s,
    )
    response = _upload_once(upload_id=upload_id, **common)
    if _staging_went_missing(response):
        from uuid import uuid4

        return _upload_once(upload_id=uuid4().hex, **common)
    return response


def _staging_went_missing(response: FunctionCallResponse) -> bool:
    if response.success:
        return False
    return getattr(response.error, "code", "") == SNAPSHOT_CHUNK_UPLOAD_MISSING_CODE


def _upload_once(
    *,
    project: Optional[str],
    repo_root: Optional[str],
    upload_id: str,
    upload: SnapshotUpload,
    defer_multi_chunk: bool,
    hook_mode: bool,
    session_id: Optional[str],
    timeout_s: Optional[float],
) -> FunctionCallResponse:
    chunks = snapshot_file_chunks(
        upload.files,
        project=project,
        repo_root=repo_root,
        upload_id=upload_id,
        hook_mode=hook_mode,
    )
    if defer_multi_chunk and len(chunks) > 1:
        abort_chunk_upload(
            project=project,
            upload_id=upload_id,
            session_id=session_id,
            timeout_s=timeout_s,
        )
        return deferral_response()
    payloads = [
        PathSnapshotChunkSyncPayload(
            project_id=project,
            repo_root=repo_root,
            upload_id=upload_id,
            operation="begin",
            snapshot=PathSnapshotChunkMetadata(
                ref=upload.label,
                commit_sha=upload.commit_sha,
                file_count=len(upload.files),
                chunk_count=len(chunks),
                symlinks=upload.symlinks,
                warnings=upload.warnings,
            ),
            hook_mode=hook_mode,
        ),
        *(
            PathSnapshotChunkSyncPayload(
                project_id=project,
                repo_root=repo_root,
                upload_id=upload_id,
                operation="append",
                chunk_index=index,
                files=files,
                hook_mode=hook_mode,
            )
            for index, files in enumerate(chunks)
        ),
        PathSnapshotChunkSyncPayload(
            project_id=project,
            repo_root=repo_root,
            upload_id=upload_id,
            operation="finalize",
            delta=upload.delta,
            hook_mode=hook_mode,
        ),
    ]
    response: Optional[FunctionCallResponse] = None
    for payload in payloads:
        response = _dispatch_or_abort(
            project, upload_id, payload, session_id, timeout_s
        )
        if not response.success:
            return response
    assert response is not None
    return response


def _dispatch_or_abort(
    project: Optional[str],
    upload_id: str,
    payload: PathSnapshotChunkSyncPayload,
    session_id: Optional[str],
    timeout_s: Optional[float],
) -> FunctionCallResponse:
    abort: Any = dict(
        project=project,
        upload_id=upload_id,
        session_id=session_id,
        timeout_s=timeout_s,
    )
    try:
        response = dispatch_chunk_payload(
            project=project,
            payload=payload,
            session_id=session_id,
            timeout_s=timeout_s,
        )
    except Exception:
        if payload.operation != "finalize":
            abort_chunk_upload(**abort)
        raise
    # A lost finalize response does not prove the server stopped. Leave its
    # staging alone; completion or the existing retention policy removes it.
    if not response.success and payload.operation != "finalize":
        abort_chunk_upload(**abort)
    return response


def dispatch_chunk_payload(
    *,
    project: Optional[str],
    payload: PathSnapshotChunkSyncPayload,
    session_id: Optional[str],
    timeout_s: Optional[float],
) -> FunctionCallResponse:
    raise_if_https_chunk_payload_too_large(payload)
    ensure_handlers_loaded()
    if payload.operation == "finalize":
        timeout_s = max(timeout_s or 0.0, FINALIZE_RESPONSE_TIMEOUT_S)
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
    "abort_chunk_upload",
    "dispatch_chunk_payload",
    "offer_begin",
    "upload_snapshot",
]
