"""GitHub App bearer-token REST helpers for the Actions command surface.

Carved out of :mod:`github_actions` to keep that orchestration module
under the authored-file line cap. Every helper dispatches through
:mod:`yoke_core.domain.gh_rest_transport` and consumes the resolved
project GitHub App auth from
:func:`yoke_core.domain.project_github_auth.resolve_project_github_auth`.

No host ``gh`` binary is required to use these helpers. Failed-log
ZIP fetch + parse lives in the sibling
:mod:`yoke_core.domain.github_actions_logs` module to keep binary
log handling out of this REST-helper file.
"""

from __future__ import annotations

import sys
from typing import Any, Dict, Mapping, Optional, Tuple

from yoke_core.domain.gh_rest_transport import (
    RestNotFoundError,
    RestRequest,
    RestTransportError,
    request_with_retry,
)
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    repair_command_hint,
    resolve_project_github_auth,
)


def resolve_token(
    project: str,
    repo: str,
    *,
    required_permissions: Mapping[str, str],
) -> str:
    """Resolve project App auth for exactly the requested bound repository."""
    try:
        resolved = resolve_project_github_auth(
            project,
            required_permissions=required_permissions,
        )
    except ProjectGithubAuthError as exc:
        print(f"Error: {exc.code}: {exc}", file=sys.stderr)
        print(f"  Repair: {repair_command_hint(exc, project)}", file=sys.stderr)
        sys.exit(4)
    requested_repo = str(repo or "").strip()
    if requested_repo.casefold() != resolved.repo.casefold():
        print(
            "Error: repository_binding_mismatch: requested repository "
            f"{requested_repo!r} does not match project '{project}' binding "
            f"{resolved.repo!r}",
            file=sys.stderr,
        )
        print(
            "  Repair: use the project's bound repository or rebind it with "
            "`yoke projects github-binding bind`",
            file=sys.stderr,
        )
        sys.exit(4)
    return resolved.token


def rest_get(
    path: str,
    *,
    query: Optional[Mapping[str, str]] = None,
    token: str,
) -> Any:
    """GET a GitHub REST endpoint; return parsed JSON body or ``None`` on 404."""
    req = RestRequest(method="GET", path=path, query=dict(query or {}))
    try:
        resp = request_with_retry(req, token=token)
    except RestNotFoundError:
        return None
    return resp.body


def rest_post(
    path: str,
    *,
    body: Mapping[str, Any],
    token: str,
    max_attempts: Optional[int] = None,
) -> Any:
    """POST to a GitHub REST endpoint; return parsed JSON body (or ``""``)."""
    req = RestRequest(method="POST", path=path, body=dict(body))
    resp = request_with_retry(
        req,
        token=token,
        max_attempts=max_attempts,
    )
    return resp.body


def run_state(repo: str, run_id: str, *, token: str) -> Tuple[int, str]:
    """Return ``(exit_code, message)`` for a workflow run state query."""
    try:
        data = rest_get(f"/repos/{repo}/actions/runs/{run_id}", token=token)
    except RestTransportError as exc:
        return 1, f"Error: failed to query run {run_id}: {exc}"
    if not isinstance(data, dict):
        return 1, f"Error: malformed response for run {run_id}"

    status = str(data.get("status") or "").strip()
    conclusion = str(data.get("conclusion") or "").strip()

    if status == "completed":
        if conclusion == "success":
            return 0, "success"
        failure = conclusion or "unknown"
        return 1, f"failed:{failure}"
    if status in ("queued", "pending", "waiting"):
        return 2, "waiting"
    if status == "in_progress":
        return 3, "in_progress"
    return 1, f"unknown:{status}"


def adaptive_wait_interval(attempt: int) -> int:
    """Return the next wait interval in seconds for workflow polling."""
    return min(30, 5 * max(1, attempt + 1))


def latest_run_id(
    repo: str,
    workflow: str,
    *,
    branch: str,
    event: str = "",
    token: str,
) -> str:
    """Return the most recent run id for a workflow on a branch, or ``""``."""
    query: Dict[str, str] = {"per_page": "1", "branch": branch}
    if event:
        query["event"] = event
    try:
        data = rest_get(
            f"/repos/{repo}/actions/workflows/{workflow}/runs",
            query=query,
            token=token,
        )
    except RestTransportError:
        return ""
    if not isinstance(data, dict):
        return ""
    runs = data.get("workflow_runs")
    if not isinstance(runs, list) or not runs:
        return ""
    first = runs[0]
    if not isinstance(first, dict):
        return ""
    raw = first.get("id")
    return str(raw) if raw not in (None, "") else ""


def latest_workflow_run(
    repo: str,
    workflow: str,
    *,
    branch: str,
    head_sha: str = "",
    token: str,
) -> Optional[Dict[str, Any]]:
    """Return the most recent matching workflow run, or ``None``.

    ``head_sha`` narrows the branch query to the exact commit being
    authorized.  Keeping the branch filter as well prevents a commit from a
    differently named ref from satisfying a branch-bound release policy.
    """
    query = {"branch": branch, "per_page": "100"}
    if head_sha:
        query["head_sha"] = head_sha
    data = rest_get(
        f"/repos/{repo}/actions/workflows/{workflow}/runs",
        query=query,
        token=token,
    )
    if not isinstance(data, dict):
        raise RestTransportError(
            "GitHub workflow-runs response must be an object"
        )
    runs = data.get("workflow_runs")
    if not isinstance(runs, list):
        raise RestTransportError(
            "GitHub workflow-runs response omitted workflow_runs"
        )
    if not runs:
        return None
    if not all(isinstance(run, dict) for run in runs):
        raise RestTransportError(
            "GitHub workflow-runs response contained a malformed run"
        )

    def _integer_field(run: Dict[str, Any], field: str) -> int:
        try:
            return int(run.get(field) or 0)
        except (TypeError, ValueError):
            return 0

    def _newest_key(run: Dict[str, Any]) -> Tuple[int, int, str, int]:
        return (
            _integer_field(run, "run_number"),
            _integer_field(run, "run_attempt"),
            str(run.get("created_at") or ""),
            _integer_field(run, "id"),
        )

    return max(runs, key=_newest_key)


__all__ = [
    "adaptive_wait_interval",
    "latest_run_id",
    "latest_workflow_run",
    "resolve_token",
    "rest_get",
    "rest_post",
    "run_state",
]
