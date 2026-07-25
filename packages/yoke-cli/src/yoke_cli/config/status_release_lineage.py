"""Report whether this checkout carries commits no release has shipped.

Deploy runs bind a release to an exact commit, so a merged fix is not live
until a release tag reaches it. Nothing surfaced that gap: `yoke status` showed
a healthy matching engine version on both the client and the server while the
newest release tag sat behind ``main``, so merged work looked shipped. In one
observed case the unreleased commit was a fix for an install that hands a fresh
managed project a gate rejecting its own rules files, and it stayed live for
every new install while appearing released.

This is deliberately an informational line rather than an issue. Commits after
the newest tag are the normal state of a repo under active development; the
answer is useful precisely because it is always visible, and an alarm that
fires on every commit would be tuned out long before the day it mattered.

Reads only the local checkout, and stays silent for a repo with no tags — a
managed project has no release lineage of its own to report.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

_GIT_TIMEOUT_S = 5


def _git(repo_root: Path, *args: str) -> str:
    """Return stripped stdout for a git command, or ``""`` on any failure."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
        )
    except (subprocess.SubprocessError, OSError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def detect(repo_root: str | Path) -> "dict[str, Any] | None":
    """Return the release-lineage summary for *repo_root*, or ``None``.

    ``None`` when the path is not a git checkout or carries no reachable tag,
    which is the ordinary case for a managed project.
    """
    root = Path(repo_root)
    tag = _git(root, "describe", "--tags", "--abbrev=0")
    if not tag:
        return None
    ahead = _git(root, "rev-list", "--count", f"{tag}..HEAD")
    try:
        unreleased = int(ahead)
    except ValueError:
        return None
    return {"newest_tag": tag, "unreleased_commits": unreleased}


def label(lineage: "dict[str, Any] | None") -> "str | None":
    """Render the one-line summary, or ``None`` when there is nothing to say."""
    if not lineage:
        return None
    tag = lineage.get("newest_tag")
    if not tag:
        return None
    count = lineage.get("unreleased_commits")
    if not isinstance(count, int) or count <= 0:
        return f"{tag} (nothing unreleased)"
    commits = "commit" if count == 1 else "commits"
    return f"{tag} + {count} unreleased {commits} — merged work is not deployed"


__all__ = ["detect", "label"]
