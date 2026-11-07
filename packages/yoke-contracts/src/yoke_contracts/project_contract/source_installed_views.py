"""Installed-layout views a Yoke source checkout generates from its sources.

An installed project receives the public docs at ``.yoke/docs`` and each
harness manifest at ``.yoke/harness/<harness>/manifest.json``. A Yoke source
checkout commits only the sources, so the teaching that names those installed
paths reads gitignored copies that ``yoke dev setup`` and the checkout's git
hooks refresh here.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict, List

from yoke_contracts.executor_labels import CANONICAL_HARNESS_IDS
from yoke_contracts.install_binding import is_yoke_source_checkout

DOCS_SOURCE = "docs/public"
DOCS_VIEW = ".yoke/docs"
HARNESS_MANIFEST_SOURCES = tuple(
    f"runtime/harness/{'claude' if harness == 'claude-code' else harness}/manifest.json"
    for harness in CANONICAL_HARNESS_IDS
)


class SourceViewError(RuntimeError):
    """The checkout's sources cannot produce its installed-layout views."""


def harness_manifest_view(source_rel: str) -> str:
    """The installed path a harness manifest source lands at."""
    return source_rel.replace("runtime/harness/", ".yoke/harness/", 1)


def view_source(rel: str) -> str:
    """The committed source a source checkout's view ``rel`` copies, else ``rel``."""
    if rel.startswith(f"{DOCS_VIEW}/"):
        return f"{DOCS_SOURCE}/{rel.removeprefix(f'{DOCS_VIEW}/')}"
    for source in HARNESS_MANIFEST_SOURCES:
        if rel == harness_manifest_view(source):
            return source
    return rel


def view_or_source_present(root: Path, rel: str) -> bool:
    """Whether ``rel`` exists, or would once ``root``'s views are generated."""
    return any((root / path).is_file() for path in (rel, view_source(rel)))


def _tracked_docs(root: Path) -> List[str]:
    try:
        listed = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--", DOCS_SOURCE],
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SourceViewError(
            f"source_view_docs_unlisted: git could not list {DOCS_SOURCE} in "
            f"{root}. Run from a Yoke source checkout with git available."
        ) from exc
    return [rel for rel in listed.decode("utf-8").split("\0") if rel]


def expected_views(root: Path) -> Dict[str, bytes]:
    """Every generated view path mapped to the bytes its source holds now."""
    sources = {
        f"{DOCS_VIEW}/{rel.removeprefix(DOCS_SOURCE + '/')}": rel
        for rel in _tracked_docs(root)
    }
    sources.update({harness_manifest_view(rel): rel for rel in HARNESS_MANIFEST_SOURCES})
    views: Dict[str, bytes] = {}
    for view, source in sorted(sources.items()):
        try:
            views[view] = (root / source).read_bytes()
        except OSError as exc:
            raise SourceViewError(
                f"source_view_source_unreadable: {source}. Restore it from git "
                "and rerun `yoke dev setup`."
            ) from exc
    return views


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _prune_docs_view(root: Path, keep: Dict[str, bytes]) -> List[str]:
    view = root / DOCS_VIEW
    if not view.is_dir():
        return []
    removed: List[str] = []
    for path in sorted(view.rglob("*"), reverse=True):
        rel = path.relative_to(root).as_posix()
        if path.is_dir() and not path.is_symlink():
            if not any(path.iterdir()):
                path.rmdir()
        elif rel not in keep:
            path.unlink()
            removed.append(rel)
    return removed


def refresh_source_installed_views(root: Path) -> List[str]:
    """Rewrite the views that differ from their sources; return changed paths.

    Anything else under ``.yoke/docs`` is removed, so a page deleted or
    renamed in ``docs/public`` disappears from the view too. Outside a Yoke
    source checkout this does nothing: there the installer owns these paths.
    """
    if not is_yoke_source_checkout(root):
        return []
    views = expected_views(root)
    changed: List[str] = []
    for rel, data in views.items():
        path = root / rel
        if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
            if path.is_symlink():
                path.unlink()
            _write(path, data)
            changed.append(rel)
    return changed + _prune_docs_view(root, views)


__all__ = [
    "DOCS_SOURCE",
    "DOCS_VIEW",
    "HARNESS_MANIFEST_SOURCES",
    "SourceViewError",
    "expected_views",
    "harness_manifest_view",
    "refresh_source_installed_views",
]
