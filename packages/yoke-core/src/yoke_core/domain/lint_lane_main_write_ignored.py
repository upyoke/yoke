"""Whether a main-checkout write target is a path the repository ignores.

The lane-main-write guard exists to keep a session's lane work out of the
main checkout's tracked source. A path the repository itself ignores is
not that source: it is a render, a capture, a scratch artifact the
checkout declares disposable, and several documented recipes write one on
main by design -- the strategy render ``yoke strategy ingest`` reads back
is written there and nowhere else. Denying those made the escape token a
routine keystroke, which is how a guard stops being read as one.

``git check-ignore`` is the authority rather than a pattern list here,
because the ignore rules are the thing being asked about and they live in
the checkout. It also answers the tracked case correctly on its own: a
path in the index is reported as NOT ignored even when a rule would match
it, so a tracked file never becomes exempt.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

#: A hook decision cannot wait on git. Longer than any local check-ignore
#: and short enough that a wedged one refuses rather than stalls a turn.
CHECK_IGNORE_TIMEOUT_SECONDS = 5.0


def is_ignored_path(target: str, repo_root: str) -> bool:
    """True when *repo_root*'s ignore rules cover *target*.

    False for anything unanswerable -- no root, an unreadable checkout, a
    git that is missing or wedged. The guard is what protects the
    checkout, so an unanswered question leaves it protecting.
    """
    if not target or not repo_root:
        return False
    try:
        result = subprocess.run(
            ["git", "-C", str(Path(repo_root)), "check-ignore", "--quiet", "--", target],
            capture_output=True,
            text=True,
            timeout=CHECK_IGNORE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    # 0 ignored, 1 not ignored, anything else (128: not a repository, bad
    # path) is an answer this cannot use.
    return result.returncode == 0


__all__ = ["CHECK_IGNORE_TIMEOUT_SECONDS", "is_ignored_path"]
