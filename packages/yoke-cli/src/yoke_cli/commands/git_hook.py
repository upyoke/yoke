"""Tool-shaped ``yoke git pre-commit`` / ``yoke git post-commit``.

The ``.git/hooks/`` shims installed by ``yoke project install``
exec these subcommands through the machine-installed ``yoke`` launcher,
so hooked commits work in external project repos without importing
``yoke_core`` or ``runtime``. They are tool-shaped CLI tokens routed by
:mod:`yoke_cli.main`, deliberately NOT dispatcher function ids (operation
inventory: ``status="permanent"``, ``reason="tool_shaped"``).

Transport honesty:

* ``git pre-commit`` runs the product-safe local gate via
  ``yoke_harness`` (staged git content + file reads). On a Yoke source
  checkout it also spawns the optional Atlas currency refresher as a
  subprocess (never imports ``yoke_core``) so stale ``docs/atlas.md`` is
  staged into the same commit. Exit 1 blocks the commit.
* ``git post-commit`` never takes local DB authority. It delegates to the
  product-safe ``yoke project snapshot sync --hook --head-only``
  scanner/dispatcher path and preserves the exit-0 degrade shape so a
  completed commit is never blocked by snapshot sync trouble.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
from typing import Callable, Dict, List, Tuple

from yoke_cli.commands.adapters.project_snapshot import project_snapshot_sync
from yoke_contracts.git_hook_markers import POST_COMMIT_SNAPSHOT_SKIP_ENV

AdapterFn = Callable[[List[str]], int]

PROJECT_ID_ENV = "YOKE_PROJECT_ID"

_PRE_COMMIT_HELP = """\
usage: yoke git pre-commit

Run the Yoke pre-commit gate against the staged content of the current
repo: diverged-files advisory, file-line-limit check, and (on a Yoke
source checkout) silent Atlas currency refresh when staged inventory
inputs make docs/atlas.md stale. Exit 1 blocks the commit; bypass with
`git commit --no-verify`.

Invoked by the `.git/hooks/pre-commit` shim that `yoke project
install` writes (both delivery strategies). Extra arguments from git are
accepted and ignored. Product-safe checks: yoke_harness.git_hooks.pre_commit;
Atlas refresh runs as `python3 -m yoke_core.tools.atlas_pre_commit_refresh`
when the source module is present."""

_POST_COMMIT_HELP = """\
usage: yoke git post-commit

Sync committed git tree state for the current checkout through
`yoke project snapshot sync --hook --head-only`. The hook scans the
just-created HEAD commit locally, dispatches the authoritative
path-snapshot write to the configured Yoke API/core, and exits 0 even
when sync needs manual repair; a completed commit is never blocked.
Gate-owned rebase replay skips this per-commit sync because the gate binds
the final lane head after the replay completes.

Invoked by the `.git/hooks/post-commit` shim that `yoke project
install` writes. Extra arguments from git are accepted and ignored."""


def _wants_help(args: List[str]) -> bool:
    return any(a in ("-h", "--help") for a in args)


def _refresh_atlas_currency_or_skip() -> None:
    """Spawn the Atlas refresher when this tree looks like Yoke source.

    Never imports ``yoke_core`` — hook-local surfaces must stay product-
    wheel safe. Missing module / non-source trees skip silently.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return
    if result.returncode != 0:
        return
    root_text = (result.stdout or "").strip()
    if not root_text:
        return
    root = pathlib.Path(root_text)
    module_path = (
        root
        / "packages"
        / "yoke-core"
        / "src"
        / "yoke_core"
        / "tools"
        / "atlas_pre_commit_refresh.py"
    )
    if not module_path.is_file():
        return
    if not (root / "docs" / "atlas.md").is_file():
        return
    env = os.environ.copy()
    core_src = str(root / "packages" / "yoke-core" / "src")
    cli_src = str(root / "packages" / "yoke-cli" / "src")
    contracts_src = str(root / "packages" / "yoke-contracts" / "src")
    harness_src = str(root / "packages" / "yoke-harness" / "src")
    prior = env.get("PYTHONPATH", "")
    parts = [core_src, cli_src, contracts_src, harness_src, str(root)]
    if prior:
        parts.append(prior)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "yoke_core.tools.atlas_pre_commit_refresh",
                "--target-root",
                str(root),
                "--stage-if-stale",
            ],
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except Exception:
        return


def git_pre_commit(args: List[str]) -> int:
    """Run the pre-commit gate; the verdict's exit code blocks the commit."""
    if _wants_help(args):
        print(_PRE_COMMIT_HELP)
        return 0
    # git passes no args to pre-commit hooks today; the shim forwards
    # "$@" for forward-compat and the gate ignores any extras (a hard
    # error here would block every commit on a git behavior change).
    _refresh_atlas_currency_or_skip()
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
    if os.environ.get(POST_COMMIT_SNAPSHOT_SKIP_ENV):
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
        "Pre-commit gate (diverged-files, file-line limit, Atlas refresh); "
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
