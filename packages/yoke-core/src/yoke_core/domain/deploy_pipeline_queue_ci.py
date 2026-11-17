"""Resolve opted-in exact-commit queue proof through the Actions read authority."""

from yoke_core.domain.ci_commit_proof import proof_run
from yoke_core.domain.github_actions_commit_runs_read import (
    CommitRunAuthorityError,
    matching_runs,
)


def queue_ci_proof(project: str, head_sha: str, workflow: str):
    """Return queue success/refusal, or let the ordinary CI gate proceed."""
    try:
        runs = matching_runs(project, head_sha, workflow)
    except CommitRunAuthorityError as exc:
        return False, (
            f"BLOCKED: queue CI proof unavailable: {exc}. "
            "Repair the project's Actions read authority and retry this run."
        )
    run = proof_run(runs, head_sha, allow_merge_group=True)
    if run is None or run.get("event") != "merge_group":
        return None
    return True, (
        f"  CI gate: {head_sha} passed in merge_group run {run['id']} "
        f"({run.get('html_url') or workflow}); no CI dispatch needed"
    )
