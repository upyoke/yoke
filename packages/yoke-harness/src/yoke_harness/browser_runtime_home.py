"""Authoritative packaged source and machine home for the Browser QA runtime.

Both the harness CLI and core QA execution materialize this package into
``~/.yoke/browser-runtime``. Keeping the package, source hash, and copy logic
here prevents a second caller from replacing the machine runtime with a
different packaged tree.
"""

from __future__ import annotations

import hashlib
import shutil
from importlib import resources
from pathlib import Path
from typing import Any, Iterator, Optional

from yoke_contracts.machine_config import reader as machine_config


RUNTIME_DIR_NAME = "browser-runtime"
# Check the full browser executable before running OS dependency setup.
CHROMIUM_PRESENT_PROBE_JS = (
    "const { chromium } = require('./node_modules/playwright'); "
    "const fs = require('node:fs'); "
    "const executable = chromium.executablePath(); "
    "if (!fs.statSync(executable).isFile()) throw new Error('Not a file: ' + executable); "
    "fs.accessSync(executable, fs.constants.X_OK); "
    "process.stdout.write('ok');"
)
HASH_MARKER_NAME = ".source-hash"
_RESOURCE_PACKAGE = "yoke_harness.browser_runtime"
_SOURCE_DIRS = ("src", "tests")
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


def declared_step_schema_bytes() -> bytes:
    """The contracts declaration the runtime copy must match."""
    from yoke_contracts.browser_step_schema import schema_bytes

    return schema_bytes()


def source_hash(source_root: Optional[Any] = None) -> str:
    root = source_root if source_root is not None else package_source_root()
    digest = hashlib.sha256()
    files = sorted(_iter_source_files(root), key=lambda entry: entry[0])
    for rel, path in files:
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    digest.update(b"contracts/browser_step_schema.json\0")
    digest.update(declared_step_schema_bytes())
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
    schema_dest = dest_root / "src" / "step-schema.json"
    schema_dest.parent.mkdir(parents=True, exist_ok=True)
    schema_dest.write_bytes(declared_step_schema_bytes())


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
