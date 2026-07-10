"""Read-only git-state checks for resumable clone onboarding.

A re-run after a partial onboarding must tell which steps already landed so it can
skip them rather than hard-fail on a half-written checkout. These pure, read-only
probes answer "is this folder already a clone of the source?" and "does origin
already point at the new repo?" — consumed by the resumable apply path
(:mod:`project_onboard`) and the idempotent remote choreography
(:mod:`project_clone_support`).

Kept dependency-free of :mod:`project_clone_support` so the import goes one way
(clone_support -> here), avoiding a cycle.
"""

from __future__ import annotations

import re
import subprocess
import urllib.parse
from pathlib import Path

from yoke_contracts import github_origin


_SCP_RE = re.compile(r"^git@(?P<host>[^:/\\]+):(?P<path>.+)$")


def remote_url(root: Path, remote: str) -> str | None:
    """Return the URL of ``remote`` in ``root``, or None when it isn't set.

    Read-only ``git remote get-url``; used by the idempotency checks so a re-run
    after a partial onboarding can tell which steps already landed.
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", remote],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    return url or None


def _canonical(url: str) -> tuple[str, str]:
    """Return ``(host, owner/repo)`` for a git URL, or a raw fallback."""
    cleaned = url.strip()
    try:
        repository = github_origin.normalize_github_repository(cleaned)
    except github_origin.GitHubApiOriginError:
        return "", cleaned.removesuffix(".git").rstrip("/")
    scp = _SCP_RE.fullmatch(cleaned)
    if scp:
        host = scp.group("host").casefold()
    else:
        host = str(urllib.parse.urlsplit(cleaned).hostname or "").casefold()
    return host, repository


def same_repo(a: str | None, b: str | None) -> bool:
    """Compare two git URLs for the same repo, ignoring transport / ``.git``.

    A prior clone may store ``origin`` as the HTTPS form of an SSH source (the
    token fallback rewrites it), so an exact string match would miss a real
    match. Normalize both to ``owner/repo`` and compare. Two URLs that don't
    resolve to a github ``owner/repo`` fall back to an exact-string compare.
    """
    if not a or not b:
        return False
    host_a, repo_a = _canonical(a)
    host_b, repo_b = _canonical(b)
    hosts_match = not host_a or not host_b or host_a == host_b
    return repo_a == repo_b and hosts_match


def existing_clone_matches(root: Path, source_url: str) -> bool:
    """True when ``root`` is already a clone of ``source_url`` (origin/upstream).

    A re-run after a partial onboarding may find the source already cloned into
    the target; this lets the apply path skip the clone (idempotent) rather than
    fail on the non-empty directory. The match is by repo identity, not exact URL
    string, so the token-fallback's HTTPS rewrite of an SSH source still counts.
    After make-it-mine / fork the source lives on ``upstream`` not ``origin``, so
    a match on either remote means the source is already present.
    """
    from yoke_cli.config.project_publish_support import is_git_repo

    if not is_git_repo(root):
        return False
    origin = remote_url(root, "origin")
    upstream = remote_url(root, "upstream")
    return same_repo(origin, source_url) or same_repo(upstream, source_url)


def origin_is(root: Path, new_origin_url: str) -> bool:
    """True when ``root``'s ``origin`` already points at ``new_origin_url``.

    Lets the re-home / fork steps skip when a prior run already re-pointed
    ``origin`` — the remote choreography is idempotent on a resume.
    """
    return same_repo(remote_url(root, "origin"), new_origin_url)


__all__ = [
    "existing_clone_matches",
    "origin_is",
    "remote_url",
    "same_repo",
]
