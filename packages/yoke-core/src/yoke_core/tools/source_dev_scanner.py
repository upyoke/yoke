"""Registered read-only scanners run from the current Yoke source checkout.

A scanner reads its own checkout and writes only ignored files, so it needs
no session, work claim or main-checkout audit. The checkout is the Git
top-level of the current directory: main, subdirectories and worktrees
behave alike.
"""

from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath
from typing import Sequence

from yoke_contracts.install_binding import is_yoke_source_checkout

READ_ONLY_SCANNER_SCRIPTS = frozenset(
    {
        "runtime/api/tools/scan_item_ref_construction.py",
        "docs/teaching/tools/build.py",
    }
)
NOT_YOKE_SOURCE_CHECKOUT = "not_yoke_source_checkout"


def checkout_root(cwd: Path | None = None) -> tuple[Path | None, str | None]:
    """Return the Yoke source checkout containing *cwd*, or a named refusal."""
    here = (cwd or Path.cwd()).resolve()
    try:
        result = subprocess.run(
            ["git", "-C", str(here), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        result = None
    top = result.stdout.strip() if result and result.returncode == 0 else ""
    root = Path(top).resolve() if top else None
    if root is None or not is_yoke_source_checkout(root):
        return None, (
            f"{NOT_YOKE_SOURCE_CHECKOUT}: {here} is not inside a Yoke source "
            "checkout; cd into a Yoke source checkout or one of its worktrees, "
            "then retry"
        )
    return root, None


def scanner_root(
    command: Sequence[str], cwd: Path | None = None
) -> tuple[Path | None, str | None] | None:
    """Resolve a registered scanner's checkout; ``None`` for other commands."""
    if len(command) < 2 or command[0] != "python3":
        return None
    named = PurePosixPath(command[1]).as_posix()
    if not any(named.endswith(script) for script in READ_ONLY_SCANNER_SCRIPTS):
        return None
    root, error = checkout_root(cwd)
    if root is None:
        return None, error
    candidate = (root / command[1]).resolve()
    try:
        relative = candidate.relative_to(root).as_posix()
    except ValueError:
        return None
    if relative not in READ_ONLY_SCANNER_SCRIPTS or not candidate.is_file():
        return None
    return root, None


__all__ = [
    "NOT_YOKE_SOURCE_CHECKOUT",
    "READ_ONLY_SCANNER_SCRIPTS",
    "checkout_root",
    "scanner_root",
]
