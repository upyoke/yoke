"""The check runs attached to one commit a merge queue is validating."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_CHECKS_READ_PERMISSION_LEVELS as CHECKS_READ,
)

from yoke_core.domain.gh_rest_transport import (
    RestRequest,
    RestTransportError,
    request_with_retry,
    split_repo,
)
from yoke_core.engines.merge_worktree_pr_queue import resolve_auth_detail
from yoke_core.engines.merge_worktree_prepare import MergeContext


@dataclass(frozen=True)
class LandingCheck:
    """One check run attached to the SHA the train is validating."""

    name: str
    status: str
    conclusion: str = ""


def read_landing_checks(
    ctx: MergeContext,
    head_sha: str,
) -> tuple[Optional[tuple[LandingCheck, ...]], Optional[str]]:
    """Per-check breakdown for the SHA the train is validating."""
    if not head_sha:
        return (), None
    auth, auth_err = resolve_auth_detail(ctx, CHECKS_READ)
    if auth_err or auth is None:
        return None, auth_err
    owner, repo = split_repo(auth.repo)
    try:
        response = request_with_retry(
            RestRequest(
                method="GET",
                path=f"/repos/{owner}/{repo}/commits/{head_sha}/check-runs",
            ),
            token=auth.token,
        )
    except RestTransportError as exc:
        return None, f"check-runs read failed: {exc}"
    payload = response.body if isinstance(response.body, dict) else None
    raw_runs = payload.get("check_runs") if payload is not None else None
    if not isinstance(raw_runs, list):
        return None, "check-runs response omitted check_runs"
    checks: list[LandingCheck] = []
    for raw in raw_runs:
        if not isinstance(raw, dict):
            return None, "check-runs response contained a malformed run"
        checks.append(
            LandingCheck(
                name=str(raw.get("name") or "unnamed check").strip(),
                status=str(raw.get("status") or "").strip().lower(),
                conclusion=str(raw.get("conclusion") or "").strip().lower(),
            )
        )
    return tuple(checks), None


__all__ = ["LandingCheck", "read_landing_checks"]
