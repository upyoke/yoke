"""Bounded, ambient-config-free Git inspection for onboarding decisions."""

from __future__ import annotations

from pathlib import Path

from yoke_cli.config import project_git_branch
from yoke_cli.config import project_git_prerequisite
from yoke_cli.config.project_git_environment import isolated_network_git_env
from yoke_cli.config.project_git_process import NetworkGitBoundaryError, run_network_git
from yoke_cli.config.project_onboard_support import ProjectOnboardError


LOCAL_GIT_TIMEOUT_SECONDS = 5.0
LOCAL_GIT_OUTPUT_MAX_BYTES = 1024 * 1024


def run(root: Path, *args: str):
    """Run one read-only Git probe without ambient routing or credentials."""

    with isolated_network_git_env(()) as env:
        return run_network_git(
            ["git", *args], cwd=root, env=env,
            timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
            maximum_output_bytes=LOCAL_GIT_OUTPUT_MAX_BYTES,
        )


def current_branch(cwd: Path) -> str:
    """Return the exact attached current branch under local Git boundaries."""

    try:
        project_git_prerequisite.require_git_available()
    except project_git_prerequisite.MissingGitError as exc:
        raise ProjectOnboardError(str(exc)) from exc
    try:
        result = run(cwd, "symbolic-ref", "--quiet", "--short", "HEAD")
    except NetworkGitBoundaryError as exc:
        raise ProjectOnboardError(
            "could not resolve the current git branch within its safety boundary"
        ) from exc
    branch = result.stdout.strip()
    if (
        result.returncode != 0
        or not project_git_branch.is_valid(branch)
    ):
        detail = result.stderr.strip() or result.stdout.strip() or "no branch"
        raise ProjectOnboardError(
            f"could not resolve the current git branch in {cwd}: {detail}"
        )
    return branch


__all__ = [
    "LOCAL_GIT_OUTPUT_MAX_BYTES",
    "LOCAL_GIT_TIMEOUT_SECONDS",
    "current_branch",
    "run",
]
