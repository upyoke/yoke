"""Quiet Atlas refresh for the installed pre-commit gate.

When staged paths touch Atlas currency inputs and ``docs/atlas.md`` is
stale, rebuild and write it under ``target_root``. A no-op (unrelated
staged set, or already current) returns ``None`` and prints nothing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence

from yoke_core.tools.atlas_currency_inputs import staged_touches_currency_inputs
from yoke_core.tools.atlas_integrity_audit import build_report
from yoke_core.tools.atlas_render_docs import is_stale, render, write


_ATLAS_RELPATH = "docs/atlas.md"


def refresh_if_stale(
    target_root: Path,
    *,
    staged_paths: Sequence[str] | None = None,
) -> Path | None:
    """Rebuild Atlas when currency inputs are staged and the doc is stale.

    Returns the written path when content changed; ``None`` when nothing
    was written. Silent on the no-op path.
    """
    root = target_root.resolve()
    if staged_paths is not None and not staged_touches_currency_inputs(
        root, staged_paths,
    ):
        return None
    report = build_report(root)
    body = render(report)
    if not is_stale(root, body=body):
        return None
    return write(root, body=body)


def stage_atlas_if_refreshed(
    target_root: Path,
    *,
    staged_paths: Sequence[str] | None = None,
) -> Path | None:
    """Refresh when needed and ``git add`` the Atlas path into the commit."""
    written = refresh_if_stale(target_root, staged_paths=staged_paths)
    if written is None:
        return None
    subprocess.run(
        ["git", "-C", str(target_root.resolve()), "add", "--", _ATLAS_RELPATH],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return written


def staged_name_only(target_root: Path) -> list[str]:
    """Return staged paths for ``target_root`` (empty on git failure)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(target_root.resolve()),
             "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line]


__all__ = [
    "refresh_if_stale",
    "stage_atlas_if_refreshed",
    "staged_name_only",
]
