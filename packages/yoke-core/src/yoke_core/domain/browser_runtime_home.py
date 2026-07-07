"""Machine-level home for the Browser QA runtime.

The Browser QA daemon is machine substrate, not repo content. Its JS
sources ship inside the Python package (``runtime/browser_runtime/``)
and are materialized on demand into ``~/.yoke/browser-runtime/`` —
the single machine-level directory where npm dependencies
(``node_modules/``), daemon state (``.daemon-state.json``,
``.daemon-stderr.log``), and the npm manifests live. Project repos and
the Yoke checkout itself never host a runnable browser runtime tree.

Materialization is hash-gated: a sha256 over the sorted relative paths
and bytes of the packaged source files is stored at
``runtime_dir()/.source-hash``. When the stored hash matches the
packaged sources, ``ensure_materialized`` is a no-op; when it differs,
``src/`` and ``tests/`` are replaced wholesale while top-level runtime
state (``node_modules/``, daemon state files) is left untouched.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Iterator, Optional

from yoke_core.domain import machine_config


RUNTIME_DIR_NAME = "browser-runtime"
HASH_MARKER_NAME = ".source-hash"

# Subtrees replaced wholesale on re-materialization.
_SOURCE_DIRS = ("src", "tests")
# Top-level files copied on re-materialization.
_SOURCE_FILES = ("package.json", "package-lock.json")


def runtime_dir() -> Path:
    """Return the machine-level Browser QA runtime directory."""

    return machine_config.yoke_home() / RUNTIME_DIR_NAME


def package_source_dir() -> Path:
    """Return the in-package root holding the packaged JS sources."""

    import runtime.browser_runtime as _pkg

    return Path(_pkg.__file__).resolve().parent


def _iter_source_files(source_root: Path) -> Iterator[Path]:
    """Yield every packaged source file under *source_root*."""

    for name in _SOURCE_FILES:
        candidate = source_root / name
        if candidate.is_file():
            yield candidate
    for dirname in _SOURCE_DIRS:
        subtree = source_root / dirname
        if not subtree.is_dir():
            continue
        for candidate in subtree.rglob("*"):
            if candidate.is_file():
                yield candidate


def source_hash(source_root: Optional[Path] = None) -> str:
    """sha256 over sorted relative paths + bytes of the packaged sources."""

    root = source_root if source_root is not None else package_source_dir()
    digest = hashlib.sha256()
    files = sorted(
        _iter_source_files(root),
        key=lambda p: p.relative_to(root).as_posix(),
    )
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _copy_sources(source_root: Path, dest_root: Path) -> None:
    """Copy packaged sources into *dest_root*, replacing subtrees wholesale.

    Only the packaged subtrees (``src/``, ``tests/``) are deleted before
    copy; top-level runtime state — ``node_modules/``, daemon state
    files, the hash marker — survives.
    """

    dest_root.mkdir(parents=True, exist_ok=True)
    for dirname in _SOURCE_DIRS:
        src_dir = source_root / dirname
        dest_dir = dest_root / dirname
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
        if src_dir.is_dir():
            shutil.copytree(src_dir, dest_dir)
    for name in _SOURCE_FILES:
        src_file = source_root / name
        if src_file.is_file():
            shutil.copy2(src_file, dest_root / name)


def ensure_materialized() -> Path:
    """Materialize the packaged sources into ``runtime_dir()`` when stale.

    Returns the runtime directory. Copying is skipped when the stored
    ``.source-hash`` matches the packaged sources' current hash.
    """

    dest = runtime_dir()
    expected = source_hash(package_source_dir())
    marker = dest / HASH_MARKER_NAME
    try:
        if marker.read_text(encoding="utf-8").strip() == expected:
            return dest
    except OSError:
        pass
    _copy_sources(package_source_dir(), dest)
    marker.write_text(expected + "\n", encoding="utf-8")
    return dest
