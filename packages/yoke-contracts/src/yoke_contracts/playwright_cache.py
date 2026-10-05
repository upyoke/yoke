"""Playwright cache locations shared by machine clients and the engine."""

from __future__ import annotations

import os


YOKE_BROWSER_CACHE_PROJECT = "yoke"


def resolve_playwright_cache(
    project_id: str | None, worktree_path: str | None
) -> str | None:
    """Resolve a project's HOME cache, a lane-local cache, or no cache."""
    if project_id:
        return os.path.join(
            os.path.expanduser("~"), ".yoke", "playwright-cache", project_id
        )
    if worktree_path:
        return os.path.join(worktree_path, ".playwright-cache")
    return None
