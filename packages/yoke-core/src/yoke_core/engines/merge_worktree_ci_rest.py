"""Merge-engine REST helpers for CI check-runs.

Carved out of :mod:`merge_worktree_pr_rest` to keep each module focused
and under the authored-file line cap. Exposes :class:`CheckRunsState`
and the state-translation table consumed by the CI orchestration in
:mod:`merge_worktree_ci`.
"""

from __future__ import annotations

from typing import NamedTuple, Optional, Tuple

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_CHECKS_READ_PERMISSION_LEVELS as CHECKS_READ,
    GITHUB_PULL_REQUESTS_READ_PERMISSION_LEVELS as PR_READ,
)
from yoke_core.domain import gh_rest_transport
from yoke_core.domain.gh_rest_transport import (
    RestAuthError,
    RestNotFoundError,
    RestRequest,
    RestTransportError,
    request_with_retry,
)
from yoke_core.engines.merge_worktree_pr_rest import (
    AuthResolutionFailed,
    resolve_auth,
)
from yoke_core.engines.merge_worktree_prepare import MergeContext


class CheckRunsState(NamedTuple):
    """Result of ``GET /repos/{o}/{r}/commits/{sha}/check-runs``."""

    states: tuple[str, ...]


# REST check-run status / conclusion pairs translated to the legacy state
# vocabulary the CI poll loop expects.
_CHECK_RUN_TO_STATE = {
    ("queued", ""): "PENDING",
    ("in_progress", ""): "PENDING",
    ("completed", "success"): "SUCCESS",
    ("completed", "failure"): "FAILURE",
    ("completed", "timed_out"): "FAILURE",
    ("completed", "action_required"): "FAILURE",
    ("completed", "cancelled"): "CANCELLED",
    ("completed", "neutral"): "NEUTRAL",
    ("completed", "skipped"): "SKIPPED",
    ("completed", "stale"): "SKIPPED",
}


def get_pr_head_sha(ctx: MergeContext, pr_num: str) -> Tuple[str, Optional[str]]:
    """Return ``(head_sha, error)`` for ``pr_num``."""
    try:
        auth = resolve_auth(ctx, required_permissions=PR_READ)
    except AuthResolutionFailed as exc:
        return "", f"auth resolution failed: {exc}"
    owner, repo = gh_rest_transport.split_repo(auth.repo)
    req = RestRequest(
        method="GET", path=f"/repos/{owner}/{repo}/pulls/{pr_num}"
    )
    try:
        resp = request_with_retry(req, token=auth.token)
    except RestTransportError as exc:
        return "", f"pulls/{pr_num} REST read failed: {exc}"
    payload = resp.body if isinstance(resp.body, dict) else {}
    head = payload.get("head")
    sha = ""
    if isinstance(head, dict):
        sha = str(head.get("sha") or "").strip()
    if not sha:
        return "", f"pulls/{pr_num} response missing head.sha"
    return sha, None


def get_check_runs(
    ctx: MergeContext, pr_num: str
) -> Tuple[Optional[CheckRunsState], Optional[str]]:
    """Fetch modern Check Runs state list for ``pr_num``'s head commit."""
    head_sha, sha_err = get_pr_head_sha(ctx, pr_num)
    if sha_err is not None:
        return None, sha_err
    try:
        auth = resolve_auth(ctx, required_permissions=CHECKS_READ)
    except AuthResolutionFailed as exc:
        return None, f"auth resolution failed: {exc}"
    owner, repo = gh_rest_transport.split_repo(auth.repo)
    req = RestRequest(
        method="GET",
        path=f"/repos/{owner}/{repo}/commits/{head_sha}/check-runs",
    )
    try:
        resp = request_with_retry(req, token=auth.token)
    except RestAuthError as exc:
        return None, f"check-runs REST authorization failed: {exc}"
    except RestNotFoundError:
        return CheckRunsState(states=()), None
    except RestTransportError as exc:
        return None, f"check-runs REST read failed: {exc}"

    payload = resp.body if isinstance(resp.body, dict) else {}
    runs = payload.get("check_runs") if isinstance(payload, dict) else None
    if not isinstance(runs, list):
        runs = []
    states: list[str] = []
    for run in runs:
        if not isinstance(run, dict):
            states.append("FAILURE")
            continue
        status = str(run.get("status") or "").strip()
        conclusion = str(run.get("conclusion") or "").strip()
        key = (status, conclusion)
        states.append(_CHECK_RUN_TO_STATE.get(key, "FAILURE"))
    return CheckRunsState(states=tuple(states)), None
