"""Chunked HTTPS dispatch for project snapshot sync."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import uuid4

from yoke_cli.commands._helpers import ensure_handlers_loaded
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
from yoke_cli.transport.https import TransportError, resolve_https_connection
from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)
from yoke_contracts.path_snapshot import (
    SNAPSHOT_SYNC_HTTPS_PAYLOAD_LIMIT_BYTES,
    PathSnapshotPayload,
    PathSnapshotSyncPayload,
    SnapshotFileEntry,
    snapshot_sync_payload_size_bytes,
)
from yoke_contracts.path_snapshot_chunks import (
    SNAPSHOT_SYNC_CHUNK_TARGET_BYTES,
    PathSnapshotChunkMetadata,
    PathSnapshotChunkSyncPayload,
    snapshot_chunk_payload_size_bytes,
)


def dispatch_chunked_sync_payload(
    *,
    project: Optional[str],
    payload: PathSnapshotSyncPayload,
    session_id: Optional[str],
    timeout_s: Optional[float],
) -> FunctionCallResponse:
    snapshots = []
    warnings = []
    project_id = None
    rows_by_commit_sha: Dict[str, Dict[str, Any]] = {}
    for snapshot in payload.snapshots:
        existing_row = rows_by_commit_sha.get(snapshot.commit_sha)
        if existing_row is not None:
            snapshots.append(_alias_snapshot_row(snapshot, existing_row))
            warnings.extend(snapshot.warnings)
            continue
        upload_id = uuid4().hex
        chunks = snapshot_file_chunks(
            project=project,
            repo_root=payload.repo_root,
            upload_id=upload_id,
            snapshot=snapshot,
            hook_mode=payload.hook_mode,
        )
        begin = PathSnapshotChunkSyncPayload(
            project_id=project,
            repo_root=payload.repo_root,
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
            hook_mode=payload.hook_mode,
        )
        response = dispatch_chunk_payload(
            project=project, payload=begin, session_id=session_id,
            timeout_s=timeout_s,
        )
        if not response.success:
            return response
        begin_result = response.result or {}
        project_id = begin_result.get("project_id", project_id)
        begin_reuse_row = _begin_reuse_row(snapshot, begin_result)
        if begin_reuse_row is not None:
            snapshots.append(begin_reuse_row)
            warnings.extend(begin_result.get("warnings") or [])
            rows_by_commit_sha[snapshot.commit_sha] = begin_reuse_row
            continue
        if payload.hook_mode:
            abort_chunk_upload(
                project=project, upload_id=upload_id,
                session_id=session_id, timeout_s=timeout_s,
            )
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
        for chunk_index, files in enumerate(chunks):
            append = PathSnapshotChunkSyncPayload(
                project_id=project,
                repo_root=payload.repo_root,
                upload_id=upload_id,
                operation="append",
                chunk_index=chunk_index,
                files=files,
                hook_mode=payload.hook_mode,
            )
            try:
                response = dispatch_chunk_payload(
                    project=project, payload=append, session_id=session_id,
                    timeout_s=timeout_s,
                )
            except Exception:
                abort_chunk_upload(
                    project=project, upload_id=upload_id,
                    session_id=session_id, timeout_s=timeout_s,
                )
                raise
            if not response.success:
                abort_chunk_upload(
                    project=project, upload_id=upload_id,
                    session_id=session_id, timeout_s=timeout_s,
                )
                return response
        finalize = PathSnapshotChunkSyncPayload(
            project_id=project,
            repo_root=payload.repo_root,
            upload_id=upload_id,
            operation="finalize",
            hook_mode=payload.hook_mode,
        )
        try:
            response = dispatch_chunk_payload(
                project=project, payload=finalize, session_id=session_id,
                timeout_s=timeout_s,
            )
        except Exception:
            abort_chunk_upload(
                project=project, upload_id=upload_id,
                session_id=session_id, timeout_s=timeout_s,
            )
            raise
        if not response.success:
            abort_chunk_upload(
                project=project, upload_id=upload_id,
                session_id=session_id, timeout_s=timeout_s,
            )
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


def snapshot_file_chunks(
    *,
    project: Optional[str],
    repo_root: Optional[str],
    upload_id: str,
    snapshot: PathSnapshotPayload,
    hook_mode: bool,
) -> List[List[SnapshotFileEntry]]:
    chunks: List[List[SnapshotFileEntry]] = []
    current: List[SnapshotFileEntry] = []
    for entry in snapshot.files:
        candidate = [*current, entry]
        if current and append_chunk_size(
            project=project,
            repo_root=repo_root,
            upload_id=upload_id,
            chunk_index=len(chunks),
            files=candidate,
            hook_mode=hook_mode,
        ) > SNAPSHOT_SYNC_CHUNK_TARGET_BYTES:
            chunks.append(current)
            current = [entry]
        else:
            current = candidate
        if append_chunk_size(
            project=project,
            repo_root=repo_root,
            upload_id=upload_id,
            chunk_index=len(chunks),
            files=current,
            hook_mode=hook_mode,
        ) > SNAPSHOT_SYNC_HTTPS_PAYLOAD_LIMIT_BYTES:
            raise ValueError(
                "one snapshot file entry is too large for HTTPS chunked "
                "snapshot sync; repair from a local-core/source-dev env"
            )
    if current:
        chunks.append(current)
    return chunks


def append_chunk_size(
    *,
    project: Optional[str],
    repo_root: Optional[str],
    upload_id: str,
    chunk_index: int,
    files: List[SnapshotFileEntry],
    hook_mode: bool,
) -> int:
    payload = PathSnapshotChunkSyncPayload(
        project_id=project,
        repo_root=repo_root,
        upload_id=upload_id,
        operation="append",
        chunk_index=chunk_index,
        files=files,
        hook_mode=hook_mode,
    )
    return snapshot_chunk_payload_size_bytes(payload)


def raise_if_https_chunk_payload_too_large(
    payload: PathSnapshotChunkSyncPayload,
) -> None:
    if not active_transport_is_https():
        return
    payload_size = snapshot_chunk_payload_size_bytes(payload)
    if payload_size <= SNAPSHOT_SYNC_HTTPS_PAYLOAD_LIMIT_BYTES:
        return
    raise ValueError(
        f"snapshot sync chunk payload is {payload_size} bytes, above the "
        "HTTPS preflight limit of "
        f"{SNAPSHOT_SYNC_HTTPS_PAYLOAD_LIMIT_BYTES} bytes"
    )


def active_transport_is_https() -> bool:
    try:
        return resolve_https_connection() is not None
    except TransportError:
        return False


def needs_https_chunking(payload: PathSnapshotSyncPayload) -> bool:
    if not active_transport_is_https():
        return False
    payload_size = snapshot_sync_payload_size_bytes(payload)
    return payload_size > SNAPSHOT_SYNC_HTTPS_PAYLOAD_LIMIT_BYTES
