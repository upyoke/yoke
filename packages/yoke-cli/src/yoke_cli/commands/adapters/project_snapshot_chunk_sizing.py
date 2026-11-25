"""Payload sizing and chunk splitting for chunked project snapshot sync."""

from __future__ import annotations

from typing import List, Optional

from yoke_cli.transport.https import TransportError, resolve_https_connection
from yoke_contracts.path_snapshot import (
    SNAPSHOT_SYNC_HTTPS_PAYLOAD_LIMIT_BYTES,
    SnapshotFileEntry,
)
from yoke_contracts.path_snapshot_chunks import (
    SNAPSHOT_SYNC_CHUNK_TARGET_BYTES,
    PathSnapshotChunkSyncPayload,
    PathSnapshotDelta,
    snapshot_chunk_payload_size_bytes,
)


def snapshot_file_chunks(
    files: List[SnapshotFileEntry],
    *,
    project: Optional[str],
    repo_root: Optional[str],
    upload_id: str,
) -> List[List[SnapshotFileEntry]]:
    """Split ``files`` into append chunks near the chunk target size.

    Each entry is serialized once: an append's JSON is its envelope plus the
    entries joined by commas, so sizes add up without re-serializing the
    growing chunk for every entry.
    """
    if not files:
        return []
    first = files[0]
    envelope = _append_size(project, repo_root, upload_id, [first])
    envelope -= _entry_size(first)
    chunks: List[List[SnapshotFileEntry]] = []
    current: List[SnapshotFileEntry] = []
    size = envelope
    for entry in files:
        entry_size = _entry_size(entry) + (1 if current else 0)
        if envelope + entry_size > SNAPSHOT_SYNC_HTTPS_PAYLOAD_LIMIT_BYTES:
            raise ValueError(
                f"snapshot file entry {entry.path!r} is too large for one "
                "chunked snapshot-sync request; repair from a "
                "local-core/source-dev env"
            )
        if current and size + entry_size > SNAPSHOT_SYNC_CHUNK_TARGET_BYTES:
            chunks.append(current)
            current, size, entry_size = [], envelope, entry_size - 1
        current.append(entry)
        size += entry_size
    chunks.append(current)
    return chunks


def delta_fits_one_request(
    delta: PathSnapshotDelta,
    *,
    project: Optional[str],
    repo_root: Optional[str],
    upload_id: str,
) -> bool:
    """Whether the finalize that carries ``delta`` stays within one chunk."""
    finalize = PathSnapshotChunkSyncPayload(
        project_id=project,
        repo_root=repo_root,
        upload_id=upload_id,
        operation="finalize",
        delta=delta,
    )
    return snapshot_chunk_payload_size_bytes(finalize) <= (
        SNAPSHOT_SYNC_CHUNK_TARGET_BYTES
    )


def _entry_size(entry: SnapshotFileEntry) -> int:
    return len(entry.model_dump_json().encode("utf-8"))


def _append_size(
    project: Optional[str],
    repo_root: Optional[str],
    upload_id: str,
    files: List[SnapshotFileEntry],
) -> int:
    payload = PathSnapshotChunkSyncPayload(
        project_id=project,
        repo_root=repo_root,
        upload_id=upload_id,
        operation="append",
        chunk_index=0,
        files=files,
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


__all__ = [
    "active_transport_is_https",
    "delta_fits_one_request",
    "raise_if_https_chunk_payload_too_large",
    "snapshot_file_chunks",
]
