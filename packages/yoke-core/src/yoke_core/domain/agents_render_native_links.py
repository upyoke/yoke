"""Native harness-directory symlinks onto rendered adapter trees.

Codex reads custom agents from ``.codex/agents`` and Cursor from
``.cursor/agents``; both are surfaced as repo-root symlinks onto the
rendered ``runtime/harness/{id}/agents`` trees. One implementation owns
target computation, idempotent (re)creation, and drift comparison for
every harness that consumes rendered adapters through a native directory.
"""

from __future__ import annotations

import os
from pathlib import Path

from yoke_core.domain.workspace_authority import (
    assert_target_under_session_work_authority,
)


def native_agents_link_target(
    target_root: Path, out_dir: Path, native_dir: Path
) -> str:
    """Relative symlink target from the native dir's parent to the rendered tree."""
    return os.path.relpath(target_root / out_dir, target_root / native_dir.parent)


def ensure_native_agents_link(
    target_root: Path,
    out_dir: Path,
    native_dir: Path,
    *,
    dry_run: bool,
) -> tuple[str, str]:
    """Ensure the harness's native agents path reaches the rendered adapters.

    Returns ``(action, target)`` where action is ``skip`` / ``would-write``
    / ``write``. Refuses to replace a non-symlink obstruction.
    """
    link_path = target_root / native_dir
    target = native_agents_link_target(target_root, out_dir, native_dir)
    if link_path.is_symlink() and os.readlink(link_path) == target:
        return "skip", target
    if dry_run:
        return "would-write", target
    assert_target_under_session_work_authority(link_path)
    link_path.parent.mkdir(parents=True, exist_ok=True)
    if link_path.is_symlink():
        link_path.unlink()
    elif link_path.exists():
        raise RuntimeError(
            f"{native_dir} exists but is not a symlink; "
            "cannot surface rendered harness agents"
        )
    link_path.symlink_to(target, target_is_directory=True)
    return "write", target


def native_agents_link_drift(
    target_root: Path, out_dir: Path, native_dir: Path
) -> list[str]:
    """Return drift descriptions for one native agents symlink."""
    link_path = target_root / native_dir
    expected_target = native_agents_link_target(target_root, out_dir, native_dir)
    if not link_path.is_symlink():
        return [f"missing: {native_dir}"]
    if os.readlink(link_path) != expected_target:
        return [f"drift: {native_dir}"]
    return []
