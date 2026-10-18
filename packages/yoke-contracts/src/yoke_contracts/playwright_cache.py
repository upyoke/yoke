"""Playwright cache locations shared by machine clients and the engine."""

from __future__ import annotations

import os
from pathlib import Path

from yoke_contracts.machine_config.paths import yoke_home


YOKE_BROWSER_CACHE_PROJECT = "yoke"


def resolve_playwright_cache(
    project_id: str | None, worktree_path: str | None
) -> str | None:
    """Resolve the selected machine home's cache, a lane cache, or no cache.

    An explicit machine home is an isolation boundary, including physical
    symlink targets. Never silently install a mission's Chromium outside it.
    """
    if project_id:
        home = yoke_home().expanduser()
        cache = home / "playwright-cache" / project_id
        if os.environ.get("YOKE_MACHINE_HOME", "").strip():
            try:
                boundary = home.resolve()
                ordinary = (Path.home() / ".yoke").resolve()
                owned = cache.resolve().is_relative_to(boundary)
                if boundary.is_relative_to(ordinary) or not owned:
                    raise ValueError("cache escapes the isolated machine home")
            except (OSError, RuntimeError, ValueError) as exc:
                raise RuntimeError(
                    f"browser_cache_not_isolated: {cache}: {exc}; set "
                    "YOKE_MACHINE_HOME to mission scratch and remove cache "
                    "symlinks escaping that directory, then retry "
                    "yoke qa browser setup."
                ) from exc
        return str(cache)
    if worktree_path:
        return os.path.join(worktree_path, ".playwright-cache")
    return None
