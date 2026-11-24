"""Playwright cache locations shared by machine clients and the engine."""

from __future__ import annotations

import os

from yoke_contracts.machine_config.paths import yoke_home


YOKE_BROWSER_CACHE_PROJECT = "yoke"


def resolve_playwright_cache(
    project_id: str | None, worktree_path: str | None
) -> str | None:
    """Resolve a project's machine-home cache, a lane-local cache, or no cache."""
    if project_id:
        return str(yoke_home() / "playwright-cache" / project_id)
    if worktree_path:
        return os.path.join(worktree_path, ".playwright-cache")
    return None
