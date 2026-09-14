"""Release-lineage and publish-sha resolution for the github-actions-workflow
stage.

Split from :mod:`yoke_core.domain.deploy_pipeline_github_workflow` to keep
that dispatch/reconciliation module under the authored-file line cap. Takes
its git-command runner as an explicit parameter, matching
:mod:`deploy_pipeline_github_workflow_reconciliation`'s established
dependency-injection shape, so the caller's own (test-patchable) ``_run_cmd``
propagates through by construction rather than by importing a second copy.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable


def resolve_release_lineage_sha(
    release_lineage: str,
    project_repo_path: str,
    gate_branch: str,
    *,
    run_cmd: Callable,
) -> tuple[str, str]:
    """Resolve a run's immutable lineage without consulting a branch head.

    Current runs bind directly to a full commit SHA. Historical release runs
    bind to an annotated release tag; for those, use only the remote tag's
    peeled commit. A lightweight tag is refused because it lacks the governed
    annotated-release boundary expected by the hosted release train.
    """
    lineage = release_lineage.strip()
    if not lineage:
        return "", (
            "github-actions-workflow requires the deployment run to carry "
            "an immutable release_lineage commit SHA or annotated release tag"
        )
    if re.fullmatch(r"[0-9a-f]{40}", lineage):
        checkout_error = verify_release_sha_in_checkout(
            lineage, project_repo_path, gate_branch, run_cmd=run_cmd,
        )
        if checkout_error:
            return "", checkout_error
        return lineage, ""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+~-]{0,127}", lineage):
        return "", (
            "deployment run release_lineage is neither an exact 40-character "
            "lowercase Git commit SHA nor a safe annotated release tag"
        )

    repo = project_repo_path or "."
    peeled_ref = f"refs/tags/{lineage}^{{}}"
    result = run_cmd(
        [
            "git", "-C", repo, "ls-remote", "origin",
            f"refs/tags/{lineage}", peeled_ref,
        ]
    )
    if result.returncode != 0:
        return "", (
            f"could not resolve annotated release tag '{lineage}' from origin"
        )
    peeled = [
        fields[0]
        for raw_line in result.stdout.splitlines()
        if len(fields := raw_line.split()) == 2
        and fields[1] == peeled_ref
        and re.fullmatch(r"[0-9a-f]{40}", fields[0])
    ]
    if len(set(peeled)) != 1:
        return "", (
            f"release_lineage '{lineage}' does not resolve to exactly one "
            "annotated release-tag commit on origin"
        )
    return peeled[0], ""


def checkout_provenance(project_repo_path: str) -> str:
    """Name where the project checkout path came from, for error messages."""
    if project_repo_path:
        return (
            "resolved from the machine-config projects mapping "
            "(~/.yoke/config.json) for this project under the active env"
        )
    return (
        "the current working directory — no machine-config projects mapping "
        "matched this project under the active env"
    )


def verify_release_sha_in_checkout(
    release_sha: str,
    project_repo_path: str,
    gate_branch: str,
    *,
    run_cmd: Callable,
) -> str:
    """Prove ``release_sha`` is an available commit without following a ref.

    Item-bound run creation separately proves that its selected commit is the
    configured environment branch head.  Execution and resume must remain
    independent of that branch afterward: an environment-level run may select
    any branch, and a saved commit stays authoritative when refs move.
    """
    del gate_branch
    repo = project_repo_path or "."
    # A worktree's .git is a file, a primary checkout's a directory — exists()
    # covers both. A dead path here is almost always a stale machine-config
    # mapping (for example, one that pointed into a since-removed worktree).
    if not (Path(repo).expanduser() / ".git").exists():
        return (
            f"project repository checkout '{repo}' "
            f"({checkout_provenance(project_repo_path)}) is missing or not "
            "a git checkout; repair or remove that projects entry, or "
            "restore the checkout"
        )
    commit_ref = f"{release_sha}^{{commit}}"
    present = run_cmd(["git", "-C", repo, "cat-file", "-e", commit_ref])
    if present.returncode == 0:
        return ""
    fetched = run_cmd([
        "git", "-C", repo, "fetch", "--quiet", "--no-tags", "origin",
        release_sha,
    ])
    if fetched.returncode == 0:
        present = run_cmd([
            "git", "-C", repo, "cat-file", "-e", commit_ref,
        ])
    if present.returncode != 0:
        # Sha-addressed fetches need the server to advertise arbitrary
        # objects, which GitHub does not; a plain ref fetch reaches every
        # pushed commit, so try that before giving up.
        run_cmd(["git", "-C", repo, "fetch", "--quiet", "--no-tags", "origin"])
        present = run_cmd([
            "git", "-C", repo, "cat-file", "-e", commit_ref,
        ])
    if present.returncode != 0:
        return (
            f"deployment run release_lineage {release_sha} is not a commit "
            f"available from the project repository at '{repo}' "
            f"({checkout_provenance(project_repo_path)}), even after "
            "fetching origin"
        )
    return ""


def resolve_publish_sha(
    project_repo_path: str,
    gate_branch: str,
    *,
    image_tag: str = "",
    run_cmd: Callable,
) -> tuple[str, str]:
    """Resolve the publish source from an explicit product pin when supplied.

    Unpinned legacy callers retain remote deploy-branch resolution; worktree
    flows without a gate branch use their local HEAD.
    """
    if image_tag:
        from yoke_core.domain.deploy_product_source import (
            DeployProductSourceError,
            resolve_product_commit,
        )

        try:
            return resolve_product_commit(project_repo_path, image_tag), ""
        except DeployProductSourceError as exc:
            return "", str(exc)
    if gate_branch:
        repo = project_repo_path or "."
        result = run_cmd(
            ["git", "-C", repo, "ls-remote", "origin", f"refs/heads/{gate_branch}"]
        )
        sha = ""
        if result.returncode == 0 and result.stdout.strip():
            sha = result.stdout.split()[0].strip()
        if not sha:
            return "", (
                f"could not resolve the deployed SHA for branch "
                f"'{gate_branch}' on origin — the branch is missing from the "
                f"remote or unreachable; push '{gate_branch}' before publishing"
            )
        return sha, ""
    command = ["git", "rev-parse", "HEAD"]
    if project_repo_path:
        command[1:1] = ["-C", project_repo_path]
    sha = run_cmd(command).stdout.strip()
    return sha, ""


__all__ = [
    "checkout_provenance",
    "resolve_publish_sha",
    "resolve_release_lineage_sha",
    "verify_release_sha_in_checkout",
]
