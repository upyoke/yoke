"""Chunked path-snapshot sync payload contracts."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from yoke_contracts.path_snapshot import (
    SNAPSHOT_PAYLOAD_VERSION,
    SnapshotFileEntry,
    SnapshotSymlinkFact,
)

SNAPSHOT_SYNC_CHUNK_TARGET_BYTES = 700_000


class PathSnapshotChunkMetadata(BaseModel):
    schema_version: int = SNAPSHOT_PAYLOAD_VERSION
    ref: str
    commit_sha: str
    file_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    symlinks: List[SnapshotSymlinkFact] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _valid_metadata(self) -> "PathSnapshotChunkMetadata":
        if self.schema_version != SNAPSHOT_PAYLOAD_VERSION:
            raise ValueError(
                f"schema_version must be {SNAPSHOT_PAYLOAD_VERSION}"
            )
        if not self.commit_sha.strip():
            raise ValueError("commit_sha is required")
        return self


class PathSnapshotChunkSyncPayload(BaseModel):
    project_id: Optional[str] = None
    repo_root: Optional[str] = None
    upload_id: str
    operation: Literal["begin", "append", "finalize", "abort"]
    snapshot: Optional[PathSnapshotChunkMetadata] = None
    chunk_index: Optional[int] = None
    files: List[SnapshotFileEntry] = Field(default_factory=list)
    hook_mode: bool = False

    @field_validator("upload_id")
    @classmethod
    def _valid_upload_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("upload_id is required")
        return cleaned

    @model_validator(mode="after")
    def _valid_operation_payload(self) -> "PathSnapshotChunkSyncPayload":
        if self.operation == "begin" and self.snapshot is None:
            raise ValueError("begin requires snapshot metadata")
        if self.operation == "append":
            if self.chunk_index is None or self.chunk_index < 0:
                raise ValueError("append requires non-negative chunk_index")
            if not self.files:
                raise ValueError("append requires at least one file entry")
        if self.operation in {"finalize", "abort"} and self.files:
            raise ValueError(f"{self.operation} must not carry files")
        return self


def snapshot_chunk_payload_size_bytes(payload: PathSnapshotChunkSyncPayload) -> int:
    """Return the UTF-8 JSON size for one chunked snapshot-sync call."""
    return len(payload.model_dump_json().encode("utf-8"))


__all__ = [
    "SNAPSHOT_SYNC_CHUNK_TARGET_BYTES",
    "PathSnapshotChunkMetadata",
    "PathSnapshotChunkSyncPayload",
    "snapshot_chunk_payload_size_bytes",
]
