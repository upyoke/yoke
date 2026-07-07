"""Shared path-snapshot payload contract and pure repo-path helpers."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import PurePosixPath
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

_LANGUAGE_BY_EXTENSION: Dict[str, str] = {
    ".py": "python", ".md": "markdown", ".json": "json",
    ".yaml": "yaml", ".yml": "yaml", ".sh": "shell",
    ".js": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".html": "html", ".css": "css", ".sql": "sql",
}


class SnapshotContractError(ValueError):
    """Raised when a path-snapshot payload is malformed."""


class DependencyScanError(Exception):
    """Raised when AST parsing fails; retained for import compatibility."""


@dataclass(frozen=True)
class ScanResult:
    edges: List[Dict[str, str]]
    error: Optional[str] = None


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

    @model_validator(mode="after")
    def _valid_payload(self) -> "PathSnapshotPayload":
        if self.schema_version != SNAPSHOT_PAYLOAD_VERSION:
            raise ValueError(
                f"schema_version must be {SNAPSHOT_PAYLOAD_VERSION}"
            )
        if not self.commit_sha.strip():
            raise ValueError("commit_sha is required")
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
                raise ValueError(
                    "symlink facts must refer to observed file entries"
                )
            if fact.reason == SYMLINK_CANONICALIZED and (
                not canonical or canonical not in observed_paths
            ):
                raise ValueError(
                    "canonicalized symlink facts must target an observed path"
                )
            if fact.reason != SYMLINK_CANONICALIZED and canonical is not None:
                raise ValueError(
                    "skipped symlink facts must not set canonical_path"
                )
        return self


class PathSnapshotSyncPayload(BaseModel):
    project_id: Optional[str] = None
    repo_root: Optional[str] = None
    snapshots: List[PathSnapshotPayload]
    hook_mode: bool = False

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
            "snapshot paths must be project-relative POSIX paths: "
            + ", ".join(invalid)
        )


def snapshot_sync_payload_size_bytes(payload: PathSnapshotSyncPayload) -> int:
    """Return the UTF-8 JSON size sent across function-call transports."""
    return len(payload.model_dump_json().encode("utf-8"))


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


def compute_line_count(source: str) -> int:
    if not source:
        return 0
    return len(source.splitlines())


def infer_language(path_string: str) -> Optional[str]:
    lower = path_string.lower()
    for ext, lang in _LANGUAGE_BY_EXTENSION.items():
        if lower.endswith(ext):
            return lang
    return None


def path_to_module(path_string: str) -> str:
    if not path_string.endswith(".py"):
        return path_string
    p = PurePosixPath(path_string)
    parts = list(p.parts)
    if parts and parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = p.stem
    if "src" in parts:
        src_index = parts.index("src")
        package_parts = parts[src_index + 1:]
        if package_parts and package_parts[0].startswith("yoke_"):
            return ".".join(package_parts)
    if parts[:2] == ["runtime", "api"]:
        return ".".join(["yoke_core", *parts[2:]])
    if parts[:2] == ["runtime", "harness"]:
        return ".".join(["yoke_harness", *parts[2:]])
    return ".".join(parts)


def compute_module_name(path_string: str) -> Optional[str]:
    if not path_string.endswith(".py"):
        return None
    return path_to_module(path_string)


def extract_edges(source: str, path_string: str) -> ScanResult:
    source_module = path_to_module(path_string)
    try:
        tree = ast.parse(source, filename=path_string)
    except SyntaxError as exc:
        return ScanResult(edges=[], error=f"SyntaxError: {exc}")
    edges: List[Dict[str, str]] = []
    import_aliases: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_module = alias.name
                imported_name = alias.asname or alias.name.split(".")[0]
                import_aliases[imported_name] = imported_module
                edges.append({
                    "source_module": source_module,
                    "imported_module": imported_module,
                    "imported_name": imported_name,
                })
        elif isinstance(node, ast.ImportFrom):
            module = _resolve_from_module(node, source_module)
            if module is None:
                continue
            for alias in node.names:
                name = alias.name
                imported_module = module
                if node.level > 0 and not node.module and name != "*":
                    imported_module = f"{module}.{name}" if module else name
                edges.append({
                    "source_module": source_module,
                    "imported_module": imported_module,
                    "imported_name": name,
                })
    _append_imported_attribute_edges(tree, source_module, import_aliases, edges)
    return ScanResult(edges=edges)


def _append_imported_attribute_edges(
    tree: ast.AST,
    source_module: str,
    import_aliases: Dict[str, str],
    edges: List[Dict[str, str]],
) -> None:
    seen = {
        (edge["source_module"], edge["imported_module"],
         edge["imported_name"])
        for edge in edges
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        value = node.value
        if not isinstance(value, ast.Name):
            continue
        imported_module = import_aliases.get(value.id)
        if not imported_module:
            continue
        triple = (source_module, imported_module, node.attr)
        if triple in seen:
            continue
        seen.add(triple)
        edges.append({
            "source_module": source_module,
            "imported_module": imported_module,
            "imported_name": node.attr,
        })


def _resolve_from_module(
    node: ast.ImportFrom, source_module: str,
) -> Optional[str]:
    if node.level == 0:
        return node.module or ""
    parts = source_module.split(".") if source_module else []
    if node.level > len(parts):
        return None
    base = parts[: len(parts) - node.level]
    if not node.module:
        return ".".join(base)
    return ".".join(base + node.module.split("."))


def file_entry_from_source(path_string: str, source: str) -> SnapshotFileEntry:
    scan = extract_edges(source, path_string) if path_string.endswith(".py") else ScanResult(edges=[])
    module_name = compute_module_name(path_string)
    edges: List[Dict[str, Any]] = list(scan.edges)
    if scan.error:
        edges = [{
            "source_module": module_name or path_string,
            "imported_module": "",
            "imported_name": "",
            "scan_error": scan.error,
        }]
    return SnapshotFileEntry(
        path=path_string,
        line_count=compute_line_count(source),
        language=infer_language(path_string),
        module_name=module_name,
        dependency_edges=edges,
        scan_error=scan.error,
    )


__all__ = """
KIND_DIRECTORY KIND_FILE ROOT_PATH_SENTINEL SNAPSHOT_PAYLOAD_VERSION
SNAPSHOT_SYNC_API_PAYLOAD_LIMIT_BYTES SNAPSHOT_SYNC_HTTPS_PAYLOAD_LIMIT_BYTES
SYMLINK_CANONICALIZED SYMLINK_DANGLING_TARGET SYMLINK_EXTERNAL_TARGET
DependencyScanError PathSnapshotPayload PathSnapshotSyncPayload ScanResult SnapshotContractError
SnapshotFileEntry SnapshotSymlinkFact all_paths_with_kinds compute_line_count
compute_module_name extract_edges file_entry_from_source infer_language
invalid_project_relative_paths parent_path_string path_to_module
snapshot_sync_payload_size_bytes""".split()
