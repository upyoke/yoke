"""Decide whether publication may push this branch at all.

Publication pushes a whole branch, so before it does it must establish that
the branch holds nothing but the installed layer. Three readings can refuse
here and each names itself: a remote that already carries the work, a remote
that could not be read, and a branch carrying commits that are not provably
this installer's — including the case where the commit list itself could not
be read, which fails closed rather than reading as "the operator owns
nothing".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.project_install import publication_outcome as outcome_layer
from yoke_cli.project_install import publication_reconcile as reconcile_layer


def push_eligibility(
    repo_root: Path, *, branch: str, remote: str, owned_paths: frozenset[str],
) -> dict[str, Any]:
    """Refuse to publish anything but the installer's own unpushed commits."""
    state = reconcile_layer.read_remote_state(
        repo_root, branch=branch, remote=remote,
    )
    if state.status == reconcile_layer.CURRENT:
        return outcome_layer.already_published(
            remote=remote, branch=branch, commit=state.local_sha,
        )
    if state.status == reconcile_layer.BEHIND:
        return outcome_layer.already_published(
            remote=remote,
            branch=branch,
            commit=state.local_sha,
            detail=f"{remote}/{branch} already carries this checkout's commits",
        )
    if state.status == reconcile_layer.FETCH_FAILED:
        return outcome_layer.pending(
            repo_root,
            remote=remote,
            branch=branch,
            detail=state.detail,
            recovery=(
                f"the remote could not be read. recipe: restore access to "
                f"{remote}, then `git push {remote} {branch}`"
            ),
        )
    if not state.commits_read:
        return outcome_layer.pending(
            repo_root,
            remote=remote,
            branch=branch,
            detail=state.detail,
            recovery=(
                "the commits this branch carries could not be listed, so it "
                "cannot be shown to hold only the installed layer and nothing "
                f"was pushed. recipe: repair the checkout so `git log "
                f"{remote}/{branch}..{branch}` succeeds, then re-run the "
                "install"
            ),
        )
    unproven = state.unproven_commits(owned_paths)
    if unproven:
        listed = "\n".join(f"  {line}" for line in unproven)
        return outcome_layer.pending(
            repo_root,
            remote=remote,
            branch=branch,
            detail=(
                f"{branch} carries commits that are not provably this "
                f"installer's:\n{listed}"
            ),
            recovery=(
                "the installed layer is committed but was not pushed, "
                "because pushing would publish those commits too. recipe: "
                f"publish or drop them yourself, then `git push {remote} "
                f"{branch}`"
            ),
        )
    return {
        "status": outcome_layer.ELIGIBLE, "remote": remote, "branch": branch,
    }

__all__ = ["push_eligibility"]
