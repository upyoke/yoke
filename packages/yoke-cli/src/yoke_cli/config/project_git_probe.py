"""Structured, bounded reachability result for one Git remote."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from yoke_cli.config import project_git_branch
from yoke_cli.config.project_git_environment import isolated_network_git_env
from yoke_cli.config.project_git_process import (
    NetworkGitBoundaryError,
    run_network_git,
)


FAILURE_ACCESS = "access"
FAILURE_NETWORK = "network"
FAILURE_OTHER = "other"


@dataclass(frozen=True)
class GitRemoteProbe:
    reachable: bool
    default_branch: str | None = None
    failure_kind: str | None = None


def probe_remote(
    url: str,
    config: tuple[str, ...],
    *,
    runner: Callable[..., object] = run_network_git,
) -> GitRemoteProbe:
    """Probe once, distinguishing access denials from generic failures."""

    try:
        with isolated_network_git_env(config, allow_protocols="https") as env:
            result = runner(
                ["git", "ls-remote", "--symref", url, "HEAD"],
                env=env,
                timeout_seconds=30,
            )
    except (OSError, NetworkGitBoundaryError):
        return GitRemoteProbe(False, failure_kind=FAILURE_NETWORK)
    if result.returncode == 0:
        return GitRemoteProbe(True, default_branch=_default_branch(result.stdout))
    failure = (
        FAILURE_ACCESS if _looks_like_access_failure(result.stderr)
        else FAILURE_OTHER
    )
    return GitRemoteProbe(False, failure_kind=failure)


def _default_branch(stdout: str) -> str | None:
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped.startswith("ref:"):
            continue
        ref = stripped[len("ref:"):].split("\t", 1)[0].strip()
        prefix = "refs/heads/"
        if ref.startswith(prefix):
            branch = ref[len(prefix):]
            if project_git_branch.is_valid(branch):
                return branch
    return None


def _looks_like_access_failure(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(needle in lowered for needle in (
        "authentication failed",
        "could not read username",
        "permission denied",
        "access denied",
        "repository not found",
        "terminal prompts disabled",
        "http 401",
        "http 403",
        "error: 401",
        "error: 403",
    ))


__all__ = [
    "FAILURE_ACCESS",
    "FAILURE_NETWORK",
    "FAILURE_OTHER",
    "GitRemoteProbe",
    "probe_remote",
]
