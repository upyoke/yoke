"""Resolve an immutable deployment lineage from a local Git remote ref."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


class DeploymentLineageResolutionError(RuntimeError):
    """A project checkout could not bind a source ref to one exact commit."""


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise DeploymentLineageResolutionError(
            "git is required to bind a deployment lineage"
        ) from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise DeploymentLineageResolutionError(
            f"git {' '.join(args)} failed in {repo}: {detail}"
        )
    return result


def resolve_commit_lineage(repo_path: str, source_ref: str) -> str:
    """Fetch ``origin`` and resolve ``source_ref`` to one full commit SHA."""
    candidate = Path(repo_path).expanduser().resolve()
    top_level = Path(
        _git(candidate, "rev-parse", "--show-toplevel").stdout.strip()
    ).resolve()
    if top_level != candidate:
        raise DeploymentLineageResolutionError(
            f"project repo path must be its Git top-level: {top_level}"
        )
    _git(candidate, "fetch", "--quiet", "--no-tags", "origin")
    commit = _git(
        candidate, "rev-parse", "--verify", f"{source_ref}^{{commit}}",
    ).stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise DeploymentLineageResolutionError(
            f"source ref {source_ref!r} did not resolve to one full commit SHA"
        )
    return commit


__all__ = [
    "DeploymentLineageResolutionError",
    "resolve_commit_lineage",
]
