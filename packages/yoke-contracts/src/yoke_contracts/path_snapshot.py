"""Shared path-snapshot payload contract and pure repo-path helpers.

Per-file source scanning that fills a file entry lives in
:mod:`yoke_contracts.path_source_scan`.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Tuple

from pydantic import BaseModel, Field, field_validator, model_validator

SNAPSHOT_PAYLOAD_VERSION = 1
SNAPSHOT_SYNC_HTTPS_PAYLOAD_LIMIT_BYTES = 900_000
SNAPSHOT_SYNC_API_PAYLOAD_LIMIT_BYTES = 25_000_000

ROOT_PATH_SENTINEL = ""
KIND_FILE = "file"
KIND_DIRECTORY = "directory"

SYMLINK_CANONICALIZED = "canonicalized"
SYMLINK_EXTERNAL_TARGET = "external_target"
SYMLINK_DANGLING_TARGET = "dangling_target"


class SnapshotContractError(ValueError):
    """Raised when a path-snapshot payload is malformed."""


class SnapshotFileEntry(BaseModel):
    path: str
    line_count: int
    language: Optional[str] = None
    module_name: Optional[str] = None
    dependency_edges: List[Dict[str, Any]] = Field(default_factory=list)
    scan_error: Optional[str] = None

    @field_validator("path")
    @classmethod
    def _valid_path(cls, value: str) -> str:
        _raise_if_invalid_paths([value])
        return value


class SnapshotSymlinkFact(BaseModel):
    path: str
    reason: Literal["canonicalized", "external_target", "dangling_target"]
    target_attempt: Optional[str] = None
    canonical_path: Optional[str] = None

    @field_validator("path")
    @classmethod
    def _valid_path(cls, value: str) -> str:
        _raise_if_invalid_paths([value])
        return value

    @field_validator("canonical_path")
    @classmethod
    def _valid_canonical(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            _raise_if_invalid_paths([value])
        return value


class PathSnapshotPayload(BaseModel):
    schema_version: int = SNAPSHOT_PAYLOAD_VERSION
    ref: str
    commit_sha: str
    files: List[SnapshotFileEntry]
    symlinks: List[SnapshotSymlinkFact] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    # False: identity-only; records the lane head and stores no snapshot.
    contents_included: bool = True

    @model_validator(mode="after")
    def _valid_payload(self) -> "PathSnapshotPayload":
        if self.schema_version != SNAPSHOT_PAYLOAD_VERSION:
            raise ValueError(f"schema_version must be {SNAPSHOT_PAYLOAD_VERSION}")
        if not self.commit_sha.strip():
            raise ValueError("commit_sha is required")
        if not self.contents_included and (self.files or self.symlinks):
            raise ValueError("an identity-only payload carries no files")
        paths = [entry.path for entry in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("files contain duplicate paths")
        symlink_paths = [fact.path for fact in self.symlinks]
        if len(symlink_paths) != len(set(symlink_paths)):
            raise ValueError("symlinks contain duplicate paths")
        file_paths = set(paths)
        observed_paths = {path for path, _kind in all_paths_with_kinds(paths)}
        for fact in self.symlinks:
            canonical = fact.canonical_path
            if fact.path not in file_paths:
                raise ValueError("symlink facts must refer to observed file entries")
            if fact.reason == SYMLINK_CANONICALIZED and (
                not canonical or canonical not in observed_paths
            ):
                raise ValueError(
                    "canonicalized symlink facts must target an observed path"
                )
            if fact.reason != SYMLINK_CANONICALIZED and canonical is not None:
                raise ValueError("skipped symlink facts must not set canonical_path")
        return self


class PathSnapshotSyncPayload(BaseModel):
    project_id: Optional[str] = None
    repo_root: Optional[str] = None
    snapshots: List[PathSnapshotPayload]

    @model_validator(mode="after")
    def _has_snapshots(self) -> "PathSnapshotSyncPayload":
        if not self.snapshots:
            raise ValueError("at least one snapshot payload is required")
        return self


def invalid_project_relative_paths(paths: Iterable[str]) -> List[str]:
    """Return paths that cannot name a project-relative path target."""
    invalid: List[str] = []
    for raw in paths:
        path = (raw or "").strip().replace("\\", "/")
        if not path:
            continue
        parts = path.split("/")
        has_invalid_part = any(part in ("", ".", "..") for part in parts)
        if path.startswith("/") or has_invalid_part:
            invalid.append(raw)
    return invalid


def _raise_if_invalid_paths(paths: Sequence[str]) -> None:
    invalid = invalid_project_relative_paths(paths)
    if invalid:
        raise SnapshotContractError(
            "snapshot paths must be project-relative POSIX paths: " + ", ".join(invalid)
        )


def snapshot_sync_payload_size_bytes(payload: PathSnapshotSyncPayload) -> int:
    """Return the UTF-8 JSON size sent across function-call transports."""
    return len(payload.model_dump_json().encode("utf-8"))


def snapshot_path_digest(file_paths: Iterable[str]) -> str:
    """SHA-256 of the sorted file paths: one inventory's path-set identity.

    An incremental sync declares it for the tree it scanned; the server
    recomputes it over the snapshot it assembled, so the two cannot drift.
    """
    joined = "\n".join(sorted(file_paths))
    return hashlib.sha256(joined.encode("utf-8", "surrogateescape")).hexdigest()


def parent_path_string(path_string: str) -> Optional[str]:
    if path_string == ROOT_PATH_SENTINEL:
        return None
    if "/" in path_string:
        return path_string.rsplit("/", 1)[0]
    return ROOT_PATH_SENTINEL


def all_paths_with_kinds(
    file_paths: Iterable[str],
) -> List[Tuple[str, str]]:
    paths = [p for p in file_paths if p]
    _raise_if_invalid_paths(paths)
    file_set: List[str] = []
    seen_dirs = {ROOT_PATH_SENTINEL}
    for fp in paths:
        file_set.append(fp)
        parent = parent_path_string(fp)
        while parent is not None and parent not in seen_dirs:
            seen_dirs.add(parent)
            parent = parent_path_string(parent)
    sorted_dirs = sorted(
        (d for d in seen_dirs if d != ROOT_PATH_SENTINEL),
        key=lambda s: (s.count("/"), s),
    )
    sorted_files = sorted(set(file_set))
    out: List[Tuple[str, str]] = [(ROOT_PATH_SENTINEL, KIND_DIRECTORY)]
    out.extend((d, KIND_DIRECTORY) for d in sorted_dirs)
    out.extend((f, KIND_FILE) for f in sorted_files)
    return out


__all__ = """
KIND_DIRECTORY KIND_FILE ROOT_PATH_SENTINEL SNAPSHOT_PAYLOAD_VERSION
SNAPSHOT_SYNC_API_PAYLOAD_LIMIT_BYTES SNAPSHOT_SYNC_HTTPS_PAYLOAD_LIMIT_BYTES
SYMLINK_CANONICALIZED SYMLINK_DANGLING_TARGET SYMLINK_EXTERNAL_TARGET
PathSnapshotPayload PathSnapshotSyncPayload SnapshotContractError
SnapshotFileEntry SnapshotSymlinkFact all_paths_with_kinds
invalid_project_relative_paths parent_path_string
snapshot_path_digest snapshot_sync_payload_size_bytes""".split()
