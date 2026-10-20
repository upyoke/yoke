"""Tool-shaped ``yoke git`` hook subcommands.

The ``.git/hooks/`` shims installed by ``yoke project install``
exec these subcommands through the machine-installed ``yoke`` launcher,
so hooked commits work in external project repos without importing
``yoke_core`` or ``runtime``. They are tool-shaped CLI tokens routed by
:mod:`yoke_cli.command_router`, deliberately NOT dispatcher function ids (operation
inventory: ``status="permanent"``, ``reason="tool_shaped"``).

Transport honesty:

* ``git pre-commit`` runs the product-safe local gate via
  ``yoke_harness`` (staged git content + file reads). On a Yoke source
  checkout it also spawns the optional Atlas currency refresher as a
  subprocess (never imports ``yoke_core``) so the ignored local
  ``docs/atlas.md`` view exists and stays current. Exit 1 blocks the commit.
* ``git post-commit``, ``git post-merge``, ``git post-rewrite`` and
  ``git post-checkout`` record this checkout's HEAD as its lane head.
  Together they fire on every git operation that moves HEAD: a commit,
  a merge or pull (fast-forward or not), the end of a rebase, and a
  branch checkout (which is how a fast-forward rebase lands). None takes
  local DB authority: each delegates to the product-safe
  ``yoke project snapshot sync --hook HOOK --head-only`` path and exits 0
  however recording fares, so a finished git operation is never failed.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
from typing import Callable, Dict, List, Tuple

from yoke_cli.commands.adapters.project_snapshot import project_snapshot_sync
from yoke_contracts.git_hook_markers import HEAD_RECORDING_SKIP_ENV
from yoke_contracts.hook_diagnostics import format_hook_diagnostic

AdapterFn = Callable[[List[str]], int]

PROJECT_ID_ENV = "YOKE_PROJECT_ID"

_PRE_COMMIT_HELP = """\
usage: yoke git pre-commit

Run the Yoke pre-commit gate against the staged content of the current
repo: diverged-files advisory, file-line-limit check, and (on a Yoke
source checkout) silent creation or currency refresh of the ignored local
docs/atlas.md view. Exit 1 blocks the commit: fix what the refusal names
(split an oversized file by responsibility) and commit again.

Invoked by the `.git/hooks/pre-commit` shim that `yoke project
install` writes (both delivery strategies). Extra arguments from git are
accepted and ignored. Product-safe checks: yoke_harness.git_hooks.pre_commit;
Atlas refresh runs as `python3 -m yoke_core.tools.atlas_pre_commit_refresh`
when the source module is present."""

_HEAD_RECORDING_HELP = """\
usage: yoke git {hook}

Record this checkout's HEAD as its lane head through
`yoke project snapshot sync --hook {hook} --head-only`. {fires}
The hook records HEAD identity only and stores no path snapshot, so it
stays inside common tool timeouts; file contents reach the path registry
through a full `yoke project snapshot sync`, which path-claim registration
also runs. Routine success stays quiet; diagnostics on stderr start with
`yoke ({hook}): `. Exits 0 even when recording needs manual repair; a
finished git operation is never failed.
Gate-owned rebase replay skips recording because the gate binds the
final lane head after the replay completes.

Invoked by the `.git/hooks/{hook}` shim that `yoke project
install` writes. Arguments from git are accepted."""

# What moves HEAD under each hook, and which invocations move nothing.
_FIRES = {
    "post-commit": "Fires after every commit, amend and rebase pick.",
    "post-merge": "Fires after every merge and pull, fast-forward or not.",
    "post-rewrite": (
        "Fires at the end of a rebase; an amend is skipped because "
        "post-commit already recorded it."
    ),
    "post-checkout": (
        "Fires after a branch checkout, which is how a fast-forward rebase "
        "lands; a file checkout or a checkout that leaves HEAD in place is "
        "skipped."
    ),
}


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
            "yoke (pre-commit): ERROR: requires yoke-harness; "
            f"install/repair the product hook package ({exc}).\n"
            "Repair the machine CLI with the public installer: "
            "curl -fsSL https://api.upyoke.com/install | bash\n"
        )
        return 1
    return int(run())


def _sync_warning(hook_name: str, reason: str) -> int:
    sys.stderr.write(
        format_hook_diagnostic(
            hook_name,
            f"lane head not recorded ({reason}); record it with "
            "`yoke project snapshot sync --head-only`.\n",
        )
    )
    return 0


def _moves_nothing(hook_name: str, args: List[str]) -> bool:
    """True for invocations whose HEAD move another hook already recorded."""
    if hook_name == "post-rewrite":
        return args[:1] == ["amend"]
    if hook_name == "post-checkout":
        # git passes: previous HEAD, new HEAD, 1 for a branch checkout.
        return len(args) < 3 or args[2] != "1" or args[0] == args[1]
    return False


def _record_head(hook_name: str, args: List[str]) -> int:
    """Never error a finished git operation; the write dispatches server-side."""
    if _wants_help(args):
        print(_HEAD_RECORDING_HELP.format(hook=hook_name, fires=_FIRES[hook_name]))
        return 0
    if os.environ.get(HEAD_RECORDING_SKIP_ENV) or _moves_nothing(hook_name, args):
        return 0
    sync_args = ["--hook", hook_name, "--head-only"]
    legacy_project = os.environ.get(PROJECT_ID_ENV)
    if legacy_project:
        sync_args.extend(["--project", legacy_project])
    try:
        rc = int(project_snapshot_sync(sync_args))
    except Exception as exc:  # never block or error a finished git operation
        return _sync_warning(hook_name, str(exc) or type(exc).__name__)
    if rc != 0:
        return _sync_warning(
            hook_name,
            f"`yoke project snapshot sync --hook {hook_name} --head-only` exited {rc}",
        )
    return 0


def git_post_commit(args: List[str]) -> int:
    return _record_head("post-commit", args)


def git_post_merge(args: List[str]) -> int:
    return _record_head("post-merge", args)


def git_post_rewrite(args: List[str]) -> int:
    return _record_head("post-rewrite", args)


def git_post_checkout(args: List[str]) -> int:
    return _record_head("post-checkout", args)


# This module's contribution to the launcher's tool-shaped table; the
# aggregate registry + resolver live in yoke_cli.commands.tool_shaped.
TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("git", "pre-commit"): git_pre_commit,
    ("git", "post-commit"): git_post_commit,
    ("git", "post-merge"): git_post_merge,
    ("git", "post-rewrite"): git_post_rewrite,
    ("git", "post-checkout"): git_post_checkout,
}

_HEAD_RECORDING_USAGE = (
    "Lane-head recording after {event}; delegates to "
    "`yoke project snapshot sync --hook {hook} --head-only` and never fails "
    "the git operation."
)

# cli form -> one-line usage for `yoke --help`.
TOOL_SHAPED_USAGE: Dict[str, str] = {
    "yoke git pre-commit": (
        "Pre-commit gate (diverged-files, file-line limit, Atlas refresh); "
        "installed .git/hooks shims exec this."
    ),
    "yoke git post-commit": _HEAD_RECORDING_USAGE.format(
        event="a commit", hook="post-commit"
    ),
    "yoke git post-merge": _HEAD_RECORDING_USAGE.format(
        event="a merge or pull", hook="post-merge"
    ),
    "yoke git post-rewrite": _HEAD_RECORDING_USAGE.format(
        event="a rebase", hook="post-rewrite"
    ),
    "yoke git post-checkout": _HEAD_RECORDING_USAGE.format(
        event="a branch checkout", hook="post-checkout"
    ),
}


__all__ = [
    "AdapterFn",
    "PROJECT_ID_ENV",
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "git_post_checkout",
    "git_post_commit",
    "git_post_merge",
    "git_post_rewrite",
    "git_pre_commit",
]
