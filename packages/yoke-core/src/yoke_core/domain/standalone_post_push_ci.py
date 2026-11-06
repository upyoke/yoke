"""Read push-owned workflow checks and prove cancellation supersession."""

from __future__ import annotations

from urllib.parse import quote

from yoke_core.domain.merge_github_authority import DIRECT_MERGE_READ_PERMISSION_LEVELS
from yoke_core.domain.gh_rest_transport import (
    RestRequest,
    RestTransportError,
    request_with_retry,
)
from yoke_core.domain.merge_github_rest import AuthResolutionFailed, resolve_auth
from yoke_core.domain.merge_context import MergeArgs, MergeContext

PER_PAGE = 100


class PushCIUnreadable(ValueError):
    """Provider evidence cannot establish push CI identity or completeness."""


def _auth(project: str, authority: str):
    return resolve_auth(
        MergeContext(args=MergeArgs(branch=""), project=project),
        required_permissions=DIRECT_MERGE_READ_PERMISSION_LEVELS,
        required_authority=authority,
    )


def _get(auth, path: str, query: dict[str, str] | None = None) -> dict:
    response = request_with_retry(
        RestRequest(method="GET", path=f"/repos/{auth.repo}/{path}", query=query or {}),
        token=auth.token,
    )
    if not isinstance(response.body, dict):
        raise PushCIUnreadable("response is not an object")
    return response.body


def _pages(auth, path: str, key: str, **query: str) -> list[dict]:
    collected = []
    expected = None
    page = 1
    while True:
        payload = _get(
            auth, path, {**query, "per_page": str(PER_PAGE), "page": str(page)}
        )
        rows, total = payload.get(key), payload.get("total_count")
        if (
            not isinstance(rows, list)
            or isinstance(total, bool)
            or not isinstance(total, int)
            or total < 0
            or any(not isinstance(row, dict) for row in rows)
        ):
            raise PushCIUnreadable(f"{key} pagination is incomplete or malformed")
        if expected is None:
            expected = total
        if expected != total:
            raise PushCIUnreadable(f"{key} pagination changed during the read")
        collected.extend(rows)
        if len(collected) == total:
            return collected
        if len(collected) > total or len(rows) < PER_PAGE:
            raise PushCIUnreadable(f"{key} pagination is incomplete or malformed")
        page += 1


def _push_runs(auth, sha: str) -> list[dict]:
    rows = _pages(auth, "actions/runs", "workflow_runs", event="push", head_sha=sha)
    if any(not row.get("event") or not row.get("head_sha") for row in rows):
        raise PushCIUnreadable("workflow run omitted event or head SHA")
    # Verify the identity even when the provider's query already filters it.
    return [
        row for row in rows if row.get("event") == "push" and row.get("head_sha") == sha
    ]


def _error(exc: Exception) -> str:
    hint = getattr(exc, "hint", "")
    return (
        f"post_push_ci_unreadable: {exc}. "
        f"Restore GitHub App Actions, Checks and Contents read access and retry merge close-out. {hint}"
    ).strip()


def read_push_checks(
    project: str, sha: str, authority: str
) -> tuple[list[dict] | None, str]:
    try:
        auth = _auth(project, authority)
        checks = []
        for run in _push_runs(auth, sha):
            suite = run.get("check_suite_id")
            if isinstance(suite, bool) or not isinstance(suite, int) or suite <= 0:
                raise PushCIUnreadable("push workflow omitted check_suite_id")
            # The workflow marker keeps queued runs and jobless cancellations visible.
            checks.append(
                {
                    "name": f"push workflow {run.get('name') or run.get('id')} on {sha}",
                    "status": run.get("status"),
                    "conclusion": run.get("conclusion"),
                    "html_url": run.get("html_url"),
                }
            )
            checks.extend(
                _pages(auth, f"check-suites/{suite}/check-runs", "check_runs")
            )
        return checks, ""
    except (AuthResolutionFailed, RestTransportError, PushCIUnreadable) as exc:
        return None, _error(exc)


def superseding_push_sha(project: str, sha: str, authority: str) -> tuple[str, str]:
    """Follow only a same-branch descendant with the cancelled workflows present."""
    try:
        auth = _auth(project, authority)
        cancelled = [
            run for run in _push_runs(auth, sha) if run.get("conclusion") == "cancelled"
        ]
        branches = {run.get("head_branch") for run in cancelled}
        if len(branches) != 1 or not all(
            isinstance(branch, str) and branch for branch in branches
        ):
            return "", ""
        branch = branches.pop()
        candidate = _get(auth, f"commits/{quote(branch, safe='')}").get("sha")
        if not isinstance(candidate, str) or len(candidate) != 40:
            raise PushCIUnreadable("branch head omitted full commit SHA")
        if candidate == sha:
            return "", ""
        comparison = _get(auth, f"compare/{sha}...{candidate}", {"per_page": "1"})
        if comparison.get("status") != "ahead":
            return "", ""
        newer = _push_runs(auth, candidate)
        workflow_ids = {
            run.get("workflow_id") for run in newer if run.get("head_branch") == branch
        }
        required = {run.get("workflow_id") for run in cancelled}
        if None in required or not required <= workflow_ids:
            return "", ""
        return candidate, ""
    except (AuthResolutionFailed, RestTransportError, PushCIUnreadable) as exc:
        return "", _error(exc)
