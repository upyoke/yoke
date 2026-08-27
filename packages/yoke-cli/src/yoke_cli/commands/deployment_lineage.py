"""Resolve an immutable deployment lineage from a local Git remote ref."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
import re
import subprocess
from pathlib import Path
from typing import Iterator

from yoke_cli.config import credentialed_git


class DeploymentLineageResolutionError(RuntimeError):
    """A project checkout could not bind a source ref to one exact commit."""


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one git command with the credential its target requires.

    Binding a lineage fetches from origin, so it authenticates with the
    machine's stored GitHub credential rather than assuming the shell that
    started the deploy carries one.
    """
    try:
        result = credentialed_git.run(["-C", str(repo), *args])
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


@contextmanager
def _ref_update_lock(repo: Path) -> Iterator[None]:
    """Serialize ref updates that share one physical Git repository."""
    common_dir = Path(
        _git(repo, "rev-parse", "--git-common-dir").stdout.strip()
    )
    if not common_dir.is_absolute():
        common_dir = (repo / common_dir).resolve()
    lock_path = common_dir / "yoke-deployment-lineage-fetch.lock"
    try:
        descriptor = os.open(
            lock_path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError as exc:
        raise DeploymentLineageResolutionError(
            f"checkout ref lock is unavailable in {common_dir}"
        ) from exc
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


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
    with _ref_update_lock(candidate):
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
