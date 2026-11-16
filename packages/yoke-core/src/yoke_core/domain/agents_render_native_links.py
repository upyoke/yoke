"""Portable native harness links onto render-owned trees and files."""

from __future__ import annotations

import os
from pathlib import Path

from yoke_core.domain.workspace_authority import (
    assert_target_under_session_work_authority,
)


def native_agents_link_target(target_root: Path, out_dir: Path, native_dir: Path) -> str:
    """Relative link target from the native path's parent."""
    return os.path.relpath(target_root / out_dir, target_root / native_dir.parent)


def _same_content(source: Path, destination: Path) -> bool:
    """Copies and junctions have the same drift contract as symlinks."""
    if source.is_file():
        return destination.is_file() and source.read_bytes() == destination.read_bytes()
    if not source.is_dir() or not destination.is_dir():
        return False
    expected = {p.relative_to(source) for p in source.rglob("*")}
    actual = {p.relative_to(destination) for p in destination.rglob("*")}
    return expected == actual and all(
        (destination / rel).is_dir() if (source / rel).is_dir()
        else (destination / rel).is_file()
        and (source / rel).read_bytes() == (destination / rel).read_bytes()
        for rel in expected
    )


def ensure_native_agents_link(
    target_root: Path, out_dir: Path, native_dir: Path, *, dry_run: bool,
) -> tuple[str, str]:
    """Create or refresh a render-owned native path using the shared OS layer."""
    from yoke_contracts.platform_links import link
    from yoke_contracts.platform_fs import remove_tree

    path = target_root / native_dir
    source = target_root / out_dir
    target = native_agents_link_target(target_root, out_dir, native_dir)
    if not native_agents_link_drift(target_root, out_dir, native_dir):
        return "skip", target
    if dry_run:
        return "would-write", target
    assert_target_under_session_work_authority(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        remove_tree(path)
    link(source, path)
    return "write", target


def native_agents_link_drift(
    target_root: Path, out_dir: Path, native_dir: Path,
) -> list[str]:
    """Compare native content, including copies made without symlink privilege."""
    path = target_root / native_dir
    if not path.exists():
        return [f"missing: {native_dir}"]
    if not _same_content(target_root / out_dir, path):
        return [f"drift: {native_dir}"]
    return []
