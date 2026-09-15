"""Read one commit's Actions runs through the project's own authority.

GitHub App private keys live on control-plane hosts, never on the machine
watching a run, so the listing is asked of the project's Actions read
authority — relayed over https, or attended-local on a source-dev machine —
exactly as every other Actions call in this codebase is.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from yoke_core.domain.json_helper import loads_text


class CommitRunAuthorityError(RuntimeError):
    """Raised when no authority can answer this project's run listing."""


def matching_runs(
    project: str,
    head_sha: str,
    workflow_name: str,
    *,
    read: Callable[..., Any] | None = None,
) -> List[Dict[str, Any]]:
    """Return the runs for exactly *head_sha*, narrowed to *workflow_name*.

    The selection itself happens where the project's installation authority
    is; this reads its answer. The ``head_sha`` equality re-check is kept on
    both sides deliberately, because this module's whole purpose is that a run
    for a neighbouring commit must never satisfy a wait.
    """
    reader = read or _relayed_commit_runs
    runs = reader(project, head_sha, workflow_name)
    return [
        run
        for run in runs
        if isinstance(run, dict)
        and str(run.get("head_sha") or "") == head_sha
        and (not workflow_name or str(run.get("name") or "") == workflow_name)
    ]


def _relayed_commit_runs(
    project: str,
    head_sha: str,
    workflow_name: str,
) -> List[Dict[str, Any]]:
    """Ask the project's Actions read authority for this commit's runs."""
    from yoke_core.domain.deploy_pipeline_reporting import _github_actions

    args = ["commit-runs", head_sha, "--json"]
    if workflow_name:
        args.extend(["--workflow", workflow_name])
    completed = _github_actions(*args, project=project)
    if completed.returncode != 0:
        raise CommitRunAuthorityError(
            (completed.stderr or completed.stdout or "").strip()
            or f"the Actions read authority refused with exit {completed.returncode}"
        )
    try:
        envelope = loads_text(completed.stdout)
    except (TypeError, ValueError) as exc:
        raise CommitRunAuthorityError(
            f"the Actions read authority returned unreadable output: {exc}"
        ) from exc
    result = envelope.get("result") if isinstance(envelope, dict) else None
    runs = result.get("runs") if isinstance(result, dict) else None
    if not isinstance(runs, list):
        raise CommitRunAuthorityError(
            "the Actions read authority returned no run listing"
        )
    return [run for run in runs if isinstance(run, dict)]

__all__ = ["CommitRunAuthorityError", "matching_runs"]
