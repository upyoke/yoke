"""Payload sizing and chunk splitting for HTTPS project snapshot sync."""

from __future__ import annotations

from typing import List, Optional

from yoke_cli.transport.https import TransportError, resolve_https_connection
from yoke_contracts.path_snapshot import (
    SNAPSHOT_SYNC_HTTPS_PAYLOAD_LIMIT_BYTES,
    PathSnapshotPayload,
    PathSnapshotSyncPayload,
    SnapshotFileEntry,
    snapshot_sync_payload_size_bytes,
)
from yoke_contracts.path_snapshot_chunks import (
    SNAPSHOT_SYNC_CHUNK_TARGET_BYTES,
    PathSnapshotChunkSyncPayload,
    snapshot_chunk_payload_size_bytes,
)


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


__all__ = [
    "active_transport_is_https",
    "append_chunk_size",
    "needs_https_chunking",
    "raise_if_https_chunk_payload_too_large",
    "snapshot_file_chunks",
]
