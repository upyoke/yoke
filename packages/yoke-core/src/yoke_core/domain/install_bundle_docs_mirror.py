"""Dogfood mirror: ``docs/public`` → ``.yoke/docs`` for source-tree teaching."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Dict, List

from yoke_core.domain.install_bundle import DOCS_DEST, DOCS_SOURCE
from yoke_core.domain.workspace_authority import (
    assert_target_under_session_work_authority,
)


def mirror_docs_dest(
    *,
    repo: Path,
    dry_run: bool,
    relative_files: Callable[[Path], List[str]],
    relative_files_raw: Callable[[Path], List[str]],
    error_cls: type[Exception],
) -> Dict[str, List[str]]:
    """Materialize authored public docs into the install destination tree."""
    source = repo / DOCS_SOURCE
    dest = repo / DOCS_DEST
    written: List[str] = []
    removed: List[str] = []
    if not source.is_dir():
        raise error_cls(f"install-bundle docs source dir is missing: {source}")
    source_files = relative_files(source)
    source_set = set(source_files)
    if dest.is_dir():
        for extra in relative_files_raw(dest):
            if extra in source_set:
                continue
            removed.append(f"{DOCS_DEST}/{extra}")
            if not dry_run:
                target = dest / extra
                assert_target_under_session_work_authority(target)
                target.unlink()
    for name in source_files:
        data = (source / name).read_bytes()
        dst = dest / name
        label = f"{DOCS_DEST}/{name}"
        if dst.is_file() and dst.read_bytes() == data:
            continue
        written.append(label)
        if not dry_run:
            assert_target_under_session_work_authority(dst)
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_suffix(dst.suffix + ".tmp")
            tmp.write_bytes(data)
            os.replace(str(tmp), str(dst))
    return {"written": written, "removed": removed}


def docs_dest_drift(
    *,
    repo: Path,
    relative_files: Callable[[Path], List[str]],
) -> List[str]:
    """Drift between authored ``docs/public`` and dogfood ``.yoke/docs``."""
    source = repo / DOCS_SOURCE
    dest = repo / DOCS_DEST
    drift: List[str] = []
    if not source.is_dir():
        drift.append(f"missing source dir: {DOCS_SOURCE}")
        return drift
    if not dest.is_dir():
        drift.append(f"missing docs dest mirror: {DOCS_DEST}")
        return drift
    source_set = set(relative_files(source))
    dest_set = set(relative_files(dest))
    for extra in sorted(dest_set - source_set):
        drift.append(f"stale docs dest file (no source): {DOCS_DEST}/{extra}")
    for missing in sorted(source_set - dest_set):
        drift.append(f"missing docs dest file: {DOCS_DEST}/{missing}")
    for name in sorted(source_set & dest_set):
        if (dest / name).read_bytes() != (source / name).read_bytes():
            drift.append(f"docs dest content drift: {DOCS_DEST}/{name}")
    return drift


def prune_empty_dirs(*, bases: list[Path], dry_run: bool) -> None:
    """Remove empty directories left after file removals."""
    for base in bases:
        if not base.exists():
            continue
        for directory in sorted(base.rglob("*"), reverse=True):
            if directory.is_dir() and not any(directory.iterdir()):
                if not dry_run:
                    assert_target_under_session_work_authority(directory)
                    directory.rmdir()
        if base.is_dir() and not any(base.iterdir()):
            if not dry_run:
                assert_target_under_session_work_authority(base)
                base.rmdir()
