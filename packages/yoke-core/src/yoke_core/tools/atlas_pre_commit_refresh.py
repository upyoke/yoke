"""Quiet Atlas refresh for the installed pre-commit gate.

When ``docs/atlas.md`` is missing, or when staged paths touch Atlas
currency inputs and the rendered view is stale, rebuild and write it
under ``target_root``. A no-op returns ``None`` and prints nothing.

Invoked from ``yoke git pre-commit`` as
``python3 -m yoke_core.tools.atlas_pre_commit_refresh`` so the product
CLI package never imports ``yoke_core`` (hook-local boundary).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from yoke_core.tools.atlas_currency_inputs import staged_touches_currency_inputs
from yoke_core.tools.atlas_integrity_audit import build_report
from yoke_core.tools.atlas_render_docs import ATLAS_RELPATH, is_stale, render, write


def refresh_if_stale(
    target_root: Path,
    *,
    staged_paths: Sequence[str] | None = None,
) -> Path | None:
    """Create a missing Atlas or refresh it after currency-input changes.

    Returns the written path when content changed; ``None`` when nothing
    was written. Silent on the no-op path.
    """
    root = target_root.resolve()
    atlas_path = root / ATLAS_RELPATH
    if (
        atlas_path.is_file()
        and staged_paths is not None
        and not staged_touches_currency_inputs(root, staged_paths)
    ):
        return None
    report = build_report(root)
    body = render(report)
    if not is_stale(root, body=body):
        return None
    return write(root, body=body)


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


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry for the pre-commit subprocess path. Always exits 0."""
    parser = argparse.ArgumentParser(
        prog="atlas_pre_commit_refresh",
        description="Quietly refresh the local docs/atlas.md view.",
    )
    parser.add_argument(
        "--target-root",
        required=True,
        help="Repository root that owns docs/atlas.md.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = Path(args.target_root).resolve()
    staged = staged_name_only(root)
    if not staged:
        return 0
    refresh_if_stale(root, staged_paths=staged)
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "main",
    "refresh_if_stale",
    "staged_name_only",
]
