"""cwd/``--rootdir`` cross-repo mismatch detection for ``watch_pytest``.

Split out of :mod:`yoke_core.tools.watch_pytest` to keep that module
under the authored-file line cap. The mismatch fires when pytest is
asked to use a rootdir whose git repo top differs from the invocation
cwd's git repo top — a hybrid run that collects tests rootdir-relative
while importing modules from cwd's ``sys.path``.
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional, Sequence


def extract_rootdir(args: Sequence[str]) -> Optional[str]:
    """Return the explicit ``--rootdir`` value from pytest args, if any."""
    seq = list(args)
    for idx, token in enumerate(seq):
        if token == "--rootdir" and idx + 1 < len(seq):
            return seq[idx + 1]
        if token.startswith("--rootdir="):
            return token.split("=", 1)[1]
    return None


def _git_toplevel(cwd: str) -> Optional[str]:
    """Return the git repo root for *cwd*, or None when not in a repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def rootdir_mismatch_warning(
    pytest_args: Sequence[str], cwd: str
) -> Optional[str]:
    """Detect cwd/rootdir mismatch and return a warning string, else None.

    The mismatch fires when pytest is asked to use a rootdir whose git
    repo top is different from the invocation cwd's git repo top. That
    shape produces a hybrid run: rootdir-relative test collection plus
    cwd-relative sys.path module resolution. The wrapper itself does not
    refuse the run — the warning is loud enough that operators see it
    in the preamble before the first progress tick.
    """
    rootdir = extract_rootdir(pytest_args)
    if not rootdir:
        return None
    rootdir_resolved = os.path.realpath(rootdir)
    cwd_resolved = os.path.realpath(cwd)
    if rootdir_resolved == cwd_resolved:
        return None
    cwd_top = _git_toplevel(cwd)
    rootdir_top = _git_toplevel(rootdir_resolved)
    # Either side outside a git repo: skip — we cannot make a confident claim.
    if cwd_top is None or rootdir_top is None:
        return None
    if os.path.realpath(cwd_top) == os.path.realpath(rootdir_top):
        return None
    return (
        f"# watch_pytest WARNING: cwd repo ({cwd_top}) and --rootdir repo "
        f"({rootdir_top}) differ. Pytest will collect tests under "
        f"{rootdir_resolved} but import modules from cwd's sys.path "
        f"({cwd_resolved}) — failures may be hybrid-run artifacts, not "
        f"real regressions. To run the rootdir's tree against its own "
        f"modules: cd {rootdir_top} && python3 -m pytest …\n"
    )
