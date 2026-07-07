"""Machine-level home for the product Browser QA runtime."""

from __future__ import annotations

import hashlib
import shutil
from importlib import resources
from pathlib import Path
from typing import Any, Iterator, Optional

from yoke_cli.config import machine_config


RUNTIME_DIR_NAME = "browser-runtime"
HASH_MARKER_NAME = ".source-hash"
_RESOURCE_PACKAGE = "yoke_harness.browser_runtime"
_SOURCE_DIRS = ("src",)
_SOURCE_FILES = ("package.json", "package-lock.json", "README.md")


def runtime_dir() -> Path:
    return machine_config.yoke_home() / RUNTIME_DIR_NAME


def package_source_root() -> Any:
    return resources.files(_RESOURCE_PACKAGE)


def _iter_source_files(source_root: Any) -> Iterator[tuple[str, Any]]:
    for name in _SOURCE_FILES:
        candidate = source_root / name
        if candidate.is_file():
            yield name, candidate
    for dirname in _SOURCE_DIRS:
        subtree = source_root / dirname
        if not subtree.is_dir():
            continue
        yield from _walk_files(subtree, dirname)


def _walk_files(root: Any, prefix: str) -> Iterator[tuple[str, Any]]:
    for candidate in root.iterdir():
        rel = f"{prefix}/{candidate.name}"
        if candidate.is_dir():
            yield from _walk_files(candidate, rel)
        elif candidate.is_file():
            yield rel, candidate


def source_hash(source_root: Optional[Any] = None) -> str:
    root = source_root if source_root is not None else package_source_root()
    digest = hashlib.sha256()
    files = sorted(_iter_source_files(root), key=lambda entry: entry[0])
    for rel, path in files:
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _copy_tree(source: Any, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        target = destination / child.name
        if child.is_dir():
            _copy_tree(child, target)
        elif child.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(child.read_bytes())


def _copy_sources(source_root: Any, dest_root: Path) -> None:
    dest_root.mkdir(parents=True, exist_ok=True)
    for dirname in _SOURCE_DIRS:
        src_dir = source_root / dirname
        dest_dir = dest_root / dirname
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
        if src_dir.is_dir():
            _copy_tree(src_dir, dest_dir)
    for name in _SOURCE_FILES:
        src_file = source_root / name
        if src_file.is_file():
            (dest_root / name).write_bytes(src_file.read_bytes())


def ensure_materialized() -> Path:
    dest = runtime_dir()
    source_root = package_source_root()
    expected = source_hash(source_root)
    marker = dest / HASH_MARKER_NAME
    try:
        if marker.read_text(encoding="utf-8").strip() == expected:
            return dest
    except OSError:
        pass
    _copy_sources(source_root, dest)
    marker.write_text(expected + "\n", encoding="utf-8")
    return dest


__all__ = [
    "HASH_MARKER_NAME",
    "RUNTIME_DIR_NAME",
    "ensure_materialized",
    "package_source_root",
    "runtime_dir",
    "source_hash",
]
