"""Machine-local runtime for lane merges through ``merge_worktree``.

An integration-lane merge pushes, opens and lands its pull request with
GitHub authority. That authority is this machine's GitHub user
authorization; the App credentials live server-side and never on a laptop.
This runtime binds the same user authority and operator-selected control
plane that ``yoke merge item`` binds, then runs the engine under them, so
the engine never falls through to reading App credentials locally.
"""

from __future__ import annotations

import importlib
import sys
from typing import List, Optional

from yoke_cli.commands.merge_item_local_runtime import (
    LocalMergeAuthorityError,
    machine_github_user_authority,
    same_universe_control_plane_authority,
)


def _engine_main(argv: List[str]) -> int:
    engine = importlib.import_module("yoke_core.engines.merge_worktree")
    return int(engine.main(argv))


def run(argv: List[str]) -> int:
    """Run the lane merge engine under its GitHub and control-plane authorities."""

    if "--help" in argv or "-h" in argv:
        return _engine_main(argv)
    with machine_github_user_authority(), same_universe_control_plane_authority():
        return _engine_main(argv)


def main(argv: Optional[List[str]] = None) -> int:
    try:
        return run(list(sys.argv[1:] if argv is None else argv))
    except LocalMergeAuthorityError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


__all__ = ["main", "run"]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
