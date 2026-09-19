"""Resolve a project branch's current head commit.

A deployment run that binds another project's source resolves each declared
branch exactly once, at start, and records the commit on the run. This is the
read behind that resolution: a plain git remote query, the same mechanism
already relied on to resolve a product's publish SHA, needing no GitHub App
or Yoke API authority.

Nothing re-resolves a branch afterwards. Which project and which branch a
stage binds is declared in the flow; this module only knows how to ask a
checkout's remote what one branch names right now.
"""

from __future__ import annotations

from typing import Tuple

from yoke_core.domain.deploy_pipeline_reporting import _run_cmd


def resolve_branch_head_sha(repo_path: str, branch: str) -> Tuple[str, str]:
    """The exact commit ``branch`` currently names in the checkout at ``repo_path``."""
    result = _run_cmd(
        ["git", "-C", repo_path, "ls-remote", "origin", f"refs/heads/{branch}"]
    )
    sha = ""
    if result.returncode == 0 and result.stdout.strip():
        sha = result.stdout.split()[0].strip()
    if not sha:
        return "", (
            f"could not resolve branch '{branch}' at '{repo_path}' via git "
            "ls-remote; missing reach fails the stage rather than binding "
            "a stale or empty value"
        )
    return sha, ""


__all__ = ["resolve_branch_head_sha"]
