"""Propose the install commit for review when its branch refuses a push.

A protected default branch is the normal shape for a real project, not an
error: it means the generated layer lands through review like any other
change. This module takes the commit the installer already made, pushes it to
its own branch, and opens the pull request for it through the project's
registered ``github.pr.create`` surface rather than a second GitHub client of
its own.

When the pull request cannot be opened — no project binding, no permission,
an unreachable control plane — the proposal branch is still pushed, so the
recovery is one named command instead of a re-run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.project_install import files as files_layer
from yoke_cli.project_install import publication_outcome as outcome_layer
from yoke_cli.project_install import publication_reconcile as reconcile_layer

PROPOSAL_BRANCH_PREFIX = "yoke-install/"
PROPOSAL_TITLE = "Install Yoke operating layer"


def propose_pull_request(
    repo_root: Path,
    *,
    remote: str,
    branch: str,
    detail: str,
    project_slug: str | None,
) -> dict[str, Any]:
    """Push the commit to its own branch and open the pull request for it."""
    commit = outcome_layer.head(repo_root)
    proposal = f"{PROPOSAL_BRANCH_PREFIX}{commit[:12]}"
    pushed = reconcile_layer.network_git(
        repo_root, "push", remote, f"{branch}:refs/heads/{proposal}",
    )
    if pushed.returncode != 0:
        refusal = pushed.stderr.strip() or pushed.stdout.strip()
        return outcome_layer.pending(
            repo_root,
            remote=remote,
            branch=branch,
            detail=f"{detail}; the proposal branch also failed: {refusal}",
            recovery=(
                f"{branch} does not accept a direct push and {proposal} could "
                f"not be pushed either. recipe: `git push {remote} "
                f"{branch}:{proposal}`, then open a pull request from "
                f"{proposal} into {branch}"
            ),
        )
    slug = project_slug or project_slug_from_manifest(repo_root)
    opened = open_pull_request(slug, head_branch=proposal, base_branch=branch)
    if opened is None:
        return outcome_layer.pending(
            repo_root,
            remote=remote,
            branch=branch,
            detail=detail,
            proposal_branch=proposal,
            recovery=(
                f"{branch} requires review, and {proposal} is pushed with the "
                f'installed layer. recipe: `yoke github pr create --title '
                f'"{PROPOSAL_TITLE}" --head {proposal} --base {branch} '
                f"--project {slug or '<project>'}`"
            ),
        )
    return {
        "status": outcome_layer.PULL_REQUEST_OPEN,
        "remote": remote,
        "branch": branch,
        "commit": commit,
        "proposal_branch": proposal,
        "pull_request": opened,
        "detail": detail,
        "recovery": (
            "the installed layer is committed locally and proposed in "
            f"{opened.get('url') or 'the pull request'}. recipe: get it "
            f"merged, then `git pull --rebase {remote} {branch}` here"
        ),
    }


def open_pull_request(
    project_slug: str | None, *, head_branch: str, base_branch: str,
) -> dict[str, Any] | None:
    """Open the pull request through the registered project GitHub surface."""
    if not project_slug:
        return None
    from yoke_contracts.api.function_call import TargetRef

    from yoke_cli.commands._helpers import ensure_handlers_loaded
    from yoke_cli.transport.dispatcher import build_actor, call_dispatcher

    ensure_handlers_loaded()
    response = call_dispatcher(
        function_id="github.pr.create",
        target=TargetRef(kind="global"),
        payload={
            "title": PROPOSAL_TITLE,
            "head": head_branch,
            "base": base_branch,
            "body": (
                "The Yoke installer generated this project's operating layer "
                f"and committed it. `{base_branch}` does not accept a direct "
                "push, so the same commit is proposed here."
            ),
            "project": project_slug,
        },
        actor=build_actor(),
    )
    if not response.success:
        return None
    result = response.result or {}
    number = result.get("number")
    if not isinstance(number, int) or number <= 0:
        return None
    return {"number": number, "url": str(result.get("url") or "")}


def project_slug_from_manifest(repo_root: Path) -> str | None:
    """Read the installed manifest's project slug, the local record of it."""
    manifest = files_layer.load_manifest(repo_root) or {}
    slug = str(manifest.get("project_slug") or "").strip()
    return slug or None


__all__ = [
    "PROPOSAL_BRANCH_PREFIX",
    "PROPOSAL_TITLE",
    "open_pull_request",
    "project_slug_from_manifest",
    "propose_pull_request",
]
