"""Ephemeral deployment workflow verification."""

from __future__ import annotations

import sys
from typing import Callable, Optional

from yoke_core.domain.ephemeral_substrate import slugify_branch
from yoke_core.domain.gh_rest_transport import RestTransportError


WorkflowRunLookup = Callable[..., Optional[dict]]


def verify_ephemeral_workflow(
    github_repo: str,
    branch: str,
    workflow: str,
    domain: str,
    commit_sha: str = "",
    *,
    project: str,
    run_lookup: WorkflowRunLookup,
) -> int:
    """Verify a successful deploy workflow and print its preview URL."""
    if not github_repo or not workflow:
        print(
            "Usage: exec_ephemeral_verify(github_repo, branch, workflow, domain, "
            "commit_sha='', project=...)",
            file=sys.stderr,
        )
        return 1
    if not branch and not commit_sha:
        print(
            "Error: at least one of <branch> or <commit_sha> must be provided",
            file=sys.stderr,
        )
        return 1
    if not domain:
        print(
            "Error: domain not provided — cannot compute preview URL",
            file=sys.stderr,
        )
        return 1

    run_data: Optional[dict] = None
    if branch:
        print(f"  Looking for ephemeral deploy run: {workflow} on branch {branch}...")
        try:
            run_data = run_lookup(
                github_repo, workflow, project=project, branch=branch,
            )
        except RestTransportError as exc:
            print(
                f"  GitHub Actions lookup failed for project '{project}': {exc}",
                file=sys.stderr,
            )
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        if run_data is None:
            print("  No run found by branch, trying SHA fallback...", file=sys.stderr)
    if run_data is None and commit_sha:
        print(f"  Looking for ephemeral deploy run: {workflow} @ {commit_sha}...")
        try:
            run_data = run_lookup(
                github_repo, workflow, project=project, commit_sha=commit_sha,
            )
        except RestTransportError as exc:
            print(
                f"  GitHub Actions lookup failed for project '{project}': {exc}",
                file=sys.stderr,
            )
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1

    if run_data is None:
        sha_label = commit_sha or "none"
        branch_label = branch or "none"
        print(
            f"  No ephemeral deploy run found (SHA: {sha_label}, branch: {branch_label})",
            file=sys.stderr,
        )
        print("  The ephemeral deploy workflow may not have triggered.", file=sys.stderr)
        return 1

    run_id = run_data.get("id", "")
    run_status = run_data.get("status", "")
    run_conclusion = run_data.get("conclusion", "") or ""
    run_created = run_data.get("created_at", "")
    print(
        f"  Found run {run_id} (status: {run_status}, conclusion: {run_conclusion}, "
        f"created: {run_created})"
    )

    if run_status != "completed":
        print(
            f"  Ephemeral deploy run {run_id} is still {run_status} — not yet complete",
            file=sys.stderr,
        )
        return 1
    if run_conclusion != "success":
        print(
            f"  Ephemeral deploy run {run_id} concluded with: {run_conclusion}",
            file=sys.stderr,
        )
        return 1

    preview_url = f"https://{slugify_branch(branch)}.{domain}"
    print("  Ephemeral deploy verified successfully")
    print(f"  Preview URL: {preview_url}")
    print(f"EPHEMERAL_URL={preview_url}")
    return 0


__all__ = ["verify_ephemeral_workflow"]
