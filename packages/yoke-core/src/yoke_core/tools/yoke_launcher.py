#!/usr/bin/env python3
"""Venv-independent ``yoke`` launcher.

This script is copied to the install-target directory (e.g. ``~/.local/bin/yoke``)
by ``install_yoke_launcher.py``. When invoked from any shell, it:

1. Reads ``YOKE_HOME`` (default ``~/yoke``) — the Yoke checkout that owns
   the in-checkout ``packages/yoke-*`` source trees.
2. Prepends ``YOKE_HOME`` and package ``src`` roots to ``sys.path`` so
   ``yoke_cli`` / ``yoke_core`` imports resolve regardless of the active
   virtualenv.
3. Dispatches ``sys.argv[1:]`` to ``yoke_cli.main.main``.

Dispatch invariant: this launcher MUST NOT itself depend on any third-party
package — only the standard library — so it stays venv-independent. All
function-call dispatch happens inside ``yoke_cli.main``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


DEFAULT_YOKE_HOME = None


def _resolve_yoke_home() -> Path:
    return Path(
        os.environ.get("YOKE_HOME")
        or DEFAULT_YOKE_HOME
        or os.path.expanduser("~/yoke")
    )


def _source_paths(home: Path) -> list[Path]:
    package_root = home / "packages"
    paths = []
    if package_root.is_dir():
        paths.extend(
            sorted(
                src
                for src in package_root.glob("*/src")
                if src.is_dir()
            )
        )
    paths.append(home)
    return paths


def _prepend_source_paths(home: Path) -> None:
    for path in reversed(_source_paths(home)):
        raw = str(path)
        if raw not in sys.path:
            sys.path.insert(0, raw)


def main() -> int:
    home = _resolve_yoke_home()
    _prepend_source_paths(home)
    from yoke_cli.main import main as cli_main

    return int(cli_main(sys.argv[1:]) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
