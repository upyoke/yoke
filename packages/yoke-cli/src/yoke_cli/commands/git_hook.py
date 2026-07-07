"""Tool-shaped ``yoke git pre-commit`` / ``yoke git post-commit``.

The ``.git/hooks/`` shims installed by ``yoke project install``
exec these subcommands through the machine-installed ``yoke`` launcher,
so hooked commits work in external project repos without importing
``yoke_core`` or ``runtime``. They are tool-shaped CLI tokens routed by
:mod:`yoke_cli.main`, deliberately NOT dispatcher function ids (operation
inventory: ``status="permanent"``, ``reason="tool_shaped"``).

Transport honesty:

* ``git pre-commit`` delegates the product-safe local gate to
  ``yoke_harness`` (staged git content + file reads). Exit 1 blocks the
  commit.
* ``git post-commit`` never takes local DB authority. It delegates to the
  product-safe ``yoke project snapshot sync --hook --head-only``
  scanner/dispatcher path and preserves the exit-0 degrade shape so a
  completed commit is never blocked by snapshot sync trouble.
"""

from __future__ import annotations

import os
import sys
from typing import Callable, Dict, List, Tuple

from yoke_cli.commands.adapters.project_snapshot import project_snapshot_sync

AdapterFn = Callable[[List[str]], int]

PROJECT_ID_ENV = "YOKE_PROJECT_ID"

_PRE_COMMIT_HELP = """\
usage: yoke git pre-commit

Run the Yoke pre-commit gate against the staged content of the current
repo: diverged-files advisory and file-line-limit check. Exit 1 blocks
the commit; bypass with `git commit --no-verify`.

Invoked by the `.git/hooks/pre-commit` shim that `yoke project
install` writes (both delivery strategies). Extra arguments from git are
accepted and ignored. Implementation: yoke_harness.git_hooks.pre_commit."""

_POST_COMMIT_HELP = """\
usage: yoke git post-commit

Sync committed git tree state for the current checkout through
`yoke project snapshot sync --hook --head-only`. The hook scans the
just-created HEAD commit locally, dispatches the authoritative
path-snapshot write to the configured Yoke API/core, and exits 0 even
when sync needs manual repair; a completed commit is never blocked.

Invoked by the `.git/hooks/post-commit` shim that `yoke project
install` writes. Extra arguments from git are accepted and ignored."""


def _wants_help(args: List[str]) -> bool:
    return any(a in ("-h", "--help") for a in args)


def git_pre_commit(args: List[str]) -> int:
    """Run the pre-commit gate; the verdict's exit code blocks the commit."""
    if _wants_help(args):
        print(_PRE_COMMIT_HELP)
        return 0
    # git passes no args to pre-commit hooks today; the shim forwards
    # "$@" for forward-compat and the gate ignores any extras (a hard
    # error here would block every commit on a git behavior change).
    try:
        from yoke_harness.git_hooks.pre_commit import run
    except ImportError as exc:
        sys.stderr.write(
            "ERROR: yoke git pre-commit requires yoke-harness; "
            f"install/repair the product hook package ({exc}).\n"
            "Use `git commit --no-verify` to bypass this check.\n"
        )
        return 1
    return int(run())


def _sync_warning(reason: str) -> int:
    sys.stderr.write(f"yoke git post-commit: snapshot sync skipped ({reason})\n")
    return 0


def git_post_commit(args: List[str]) -> int:
    """Never error a completed commit; snapshot writes dispatch server-side."""
    if _wants_help(args):
        print(_POST_COMMIT_HELP)
        return 0
    sync_args = ["--hook", "--head-only"]
    legacy_project = os.environ.get(PROJECT_ID_ENV)
    if legacy_project:
        sync_args.extend(["--project", legacy_project])
    try:
        rc = int(project_snapshot_sync(sync_args))
    except Exception as exc:  # never block or error a completed commit
        return _sync_warning(str(exc) or type(exc).__name__)
    if rc != 0:
        return _sync_warning(
            f"`yoke project snapshot sync --hook --head-only` exited {rc}"
        )
    return 0


# This module's contribution to the launcher's tool-shaped table; the
# aggregate registry + resolver live in yoke_cli.commands.tool_shaped.
TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("git", "pre-commit"): git_pre_commit,
    ("git", "post-commit"): git_post_commit,
}

# cli form -> one-line usage for `yoke --help`.
TOOL_SHAPED_USAGE: Dict[str, str] = {
    "yoke git pre-commit": (
        "Pre-commit gate (diverged-files advisory, file-line limit); "
        "installed .git/hooks shims exec this."
    ),
    "yoke git post-commit": (
        "Post-commit path snapshot sync; delegates to "
        "`yoke project snapshot sync --hook --head-only` and never blocks "
        "the commit."
    ),
}


__all__ = [
    "AdapterFn",
    "PROJECT_ID_ENV",
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "git_post_commit",
    "git_pre_commit",
]
