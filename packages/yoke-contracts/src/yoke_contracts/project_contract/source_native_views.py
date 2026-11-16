"""Native harness views onto render-owned trees and files.

Each harness discovers its agents, rules, skills or hooks at a fixed native
path (``.claude/agents``, ``.codex/hooks.json`` ...). A Yoke source checkout
tracks only the rendered sources under ``runtime/harness`` and ``.agents``;
the native paths are gitignored views that ``yoke agents render`` and
``refresh_source_installed_views`` (run by ``yoke dev setup``, lane
preparation and the checkout's head-moving git hooks) recreate. ``platform_links`` chooses a
symlink, a junction or a copy, so drift compares content, not link targets.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional, Tuple

# (native path, render-owned source), both relative to the checkout root.
NATIVE_AGENT_LINKS: Tuple[Tuple[Path, Path], ...] = (
    (Path(".claude/agents"), Path("runtime/harness/claude/agents")),
    (Path(".claude/rules"), Path("runtime/harness/claude/rules")),
    (Path(".claude/skills/yoke"), Path(".agents/skills/yoke")),
    (Path(".codex/hooks.json"), Path("runtime/harness/codex/hooks.json")),
    (Path(".codex/agents"), Path("runtime/harness/codex/agents")),
    (Path(".cursor/agents"), Path("runtime/harness/cursor/agents")),
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
    target_root: Path,
    out_dir: Path,
    native_dir: Path,
    *,
    dry_run: bool,
    before_write: Optional[Callable[[Path], None]] = None,
) -> tuple[str, str]:
    """Create or refresh a render-owned native path using the shared OS layer.

    ``before_write`` sees the native path just before it is replaced, so a
    caller can refuse a write outside its authority.
    """
    from yoke_contracts.platform_fs import remove_tree
    from yoke_contracts.platform_links import link

    path = target_root / native_dir
    source = target_root / out_dir
    target = native_agents_link_target(target_root, out_dir, native_dir)
    if not native_agents_link_drift(target_root, out_dir, native_dir):
        return "skip", target
    if dry_run:
        return "would-write", target
    if before_write is not None:
        before_write(path)
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
        return [f"missing: {native_dir.as_posix()}"]
    if not _same_content(target_root / out_dir, path):
        return [f"drift: {native_dir.as_posix()}"]
    return []


__all__ = [
    "NATIVE_AGENT_LINKS",
    "ensure_native_agents_link",
    "native_agents_link_drift",
    "native_agents_link_target",
]
