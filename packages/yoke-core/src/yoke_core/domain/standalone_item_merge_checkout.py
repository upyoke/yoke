"""Checkout the standalone merge lands in.

The lane was prepared in the checkout the item's project maps to, so the
merge reads the same mapping through the shared preflight resolver.
Deriving it from the session's own repo instead merged — or refused —
against whichever repository the harness happened to stand in.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def resolve_checkout(item: dict[str, Any], target_override: str) -> tuple[Path, str]:
    """Resolve the checkout and base branch the ITEM's branch lands in."""
    from yoke_core.domain.worktree_preflight_repo_resolution import (
        resolve_preflight_lane_target,
    )
    from yoke_core.engines.done_transition_gates import (
        _get_base_branch,
        _resolve_default_branch,
    )

    lane_target = resolve_preflight_lane_target(
        item=item, project_flag=None, repo_root_override=None,
    )
    if lane_target.error:
        raise RuntimeError(lane_target.error)
    project_repo = Path(lane_target.repo_root)
    project_slug = lane_target.project_slug
    default_branch = (
        _resolve_default_branch(project_slug) if project_slug else ""
    )
    target = target_override or _get_base_branch(default_branch, project_repo)
    return project_repo, target or "main"


def ensure_usable_cwd(repo_root: Path, lane_root: str) -> bool:
    """Move out of a lane before merge close-out can remove that directory."""

    try:
        current = Path.cwd().resolve()
    except OSError:
        os.chdir(repo_root)
        return True
    if not lane_root:
        return False
    try:
        lane = Path(lane_root).expanduser().resolve()
    except OSError:
        return False
    if current != lane and lane not in current.parents:
        return False
    os.chdir(repo_root)
    return True


__all__ = ["ensure_usable_cwd", "resolve_checkout"]
