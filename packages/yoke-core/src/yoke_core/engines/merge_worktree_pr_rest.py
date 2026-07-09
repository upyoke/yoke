"""Merge-engine PR REST helpers.

Direct REST calls through :mod:`yoke_core.domain.gh_rest_transport`
for the pull-request operations the merge engine drives. Token
resolution flows through
:func:`yoke_core.domain.project_github_auth.resolve_project_github_auth`
exactly once per helper invocation — no second secret-storage shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from yoke_core.domain import gh_rest_transport
from yoke_core.domain.gh_rest_transport import (
    RestAuthError,
    RestNotFoundError,
    RestRequest,
    RestServerError,
    RestTransportError,
    RestUnprocessableError,
    request_with_retry,
)
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuth,
    ProjectGithubAuthError,
    repair_command_hint,
    resolve_project_github_auth,
)
from yoke_core.engines.merge_worktree_prepare import MergeContext


# ---------------------------------------------------------------------------
# Result shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PrCreateResult:
    """Outcome of ``POST /repos/{o}/{r}/pulls``."""

    pr_url: str
    pr_num: str
    already_exists: bool = False
    error_detail: Optional[str] = None  # populated on hard failure only


@dataclass(frozen=True)
class PrMergeStateResult:
    """Outcome of ``GET /repos/{o}/{r}/pulls/{n}`` mergeability fields."""

    merge_state_status: str  # "clean" | "blocked" | ...
    mergeable: str  # "true" | "false" | "unknown" (lowercased strings)


@dataclass(frozen=True)
class PrMergeResult:
    """Outcome of ``PUT /repos/{o}/{r}/pulls/{n}/merge``."""

    success: bool
    error_detail: Optional[str] = None
    retryable_signature: Optional[str] = None


# ---------------------------------------------------------------------------
# Auth wiring (shared per-helper)
# ---------------------------------------------------------------------------


class AuthResolutionFailed(Exception):
    """Project auth resolution raised before any HTTP request could go out."""

    def __init__(self, message: str, *, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


def resolve_auth(ctx: MergeContext) -> ProjectGithubAuth:
    """Resolve the project's GitHub auth bundle for this merge.

    Raises :class:`AuthResolutionFailed` carrying a repair hint when the
    project capability / secret / repo metadata is incomplete.
    """
    project = ctx.project or ""
    if not project or project == "null":
        raise AuthResolutionFailed(
            "merge context has no project; REST transport requires project auth"
        )
    try:
        return resolve_project_github_auth(project)
    except ProjectGithubAuthError as exc:
        hint = repair_command_hint(exc, project)
        raise AuthResolutionFailed(
            f"{exc.code}: {exc}", hint=hint
        ) from exc


def validate_github_auth_for_merge(ctx: MergeContext) -> Tuple[bool, Optional[str]]:
    """Cheap precondition check used by ``merge_worktree_runner.run``.

    Returns ``(True, None)`` when the resolver succeeds and the bearer token
    is non-empty. Returns ``(False, message)`` when the resolver fails, with
    ``message`` already including the repair hint so callers can fail-fast
    with one operator-actionable line.
    """
    try:
        auth = resolve_auth(ctx)
    except AuthResolutionFailed as exc:
        message = f"Error: {exc}"
        if exc.hint:
            message = f"{message}\n  Repair: {exc.hint}"
        return False, message
    if not auth.token:
        return False, (
            f"Error: project '{ctx.project}' resolved an empty GitHub bearer token; "
            "reconnect the GitHub App installation or refresh the repo binding"
        )
    return True, None


# ---------------------------------------------------------------------------
# PR create / discover
# ---------------------------------------------------------------------------


def create_pr(
    ctx: MergeContext,
    *,
    title: str,
    body: str,
) -> PrCreateResult:
    """Create a pull request via REST.

    Returns :class:`PrCreateResult` with ``pr_url``/``pr_num`` populated on
    success, or ``already_exists=True`` when GitHub returns 422 with the
    documented "A pull request already exists" message. Hard failures
    return with ``error_detail`` populated and ``pr_url``/``pr_num`` empty.
    """
    auth = resolve_auth(ctx)
    owner, repo = gh_rest_transport.split_repo(auth.repo)
    req = RestRequest(
        method="POST",
        path=f"/repos/{owner}/{repo}/pulls",
        body={
            "title": title,
            "head": ctx.args.branch,
            "base": ctx.args.target,
            "body": body,
        },
    )
    try:
        resp = request_with_retry(req, token=auth.token)
    except RestUnprocessableError as exc:
        body_text = (exc.body or "") + " " + str(exc)
        lowered = body_text.lower()
        if (
            "already exists" in lowered
            or "a pull request for branch" in lowered
            or "pull request already exists" in lowered
        ):
            return PrCreateResult(pr_url="", pr_num="", already_exists=True)
        return PrCreateResult(
            pr_url="", pr_num="",
            error_detail=f"pr create rejected (HTTP {exc.status}): {exc}",
        )
    except RestTransportError as exc:
        return PrCreateResult(
            pr_url="", pr_num="",
            error_detail=f"pr create failed: {exc}",
        )

    payload = resp.body if isinstance(resp.body, dict) else {}
    url = str(payload.get("html_url") or payload.get("url") or "").strip()
    number_val = payload.get("number")
    pr_num = str(number_val).strip() if number_val is not None else ""
    if not url or not pr_num:
        return PrCreateResult(
            pr_url="", pr_num="",
            error_detail=(
                "pr create returned 2xx but PR identifiers are empty "
                f"(url={url!r}, number={number_val!r})"
            ),
        )
    return PrCreateResult(pr_url=url, pr_num=pr_num)


def find_existing_pr(
    ctx: MergeContext,
) -> Tuple[Optional[str], Optional[str]]:
    """Look up an existing open PR for ``ctx.args.branch`` via REST.

    Returns ``(pr_url, pr_num)`` on success, ``(None, None)`` when no open
    PR exists or discovery itself fails.
    """
    try:
        auth = resolve_auth(ctx)
    except AuthResolutionFailed:
        return None, None
    owner, repo = gh_rest_transport.split_repo(auth.repo)
    req = RestRequest(
        method="GET",
        path=f"/repos/{owner}/{repo}/pulls",
        query={"head": f"{owner}:{ctx.args.branch}", "state": "open"},
    )
    try:
        resp = request_with_retry(req, token=auth.token)
    except RestTransportError:
        return None, None

    items = resp.body if isinstance(resp.body, list) else []
    if not items:
        return None, None
    first = items[0]
    if not isinstance(first, dict):
        return None, None
    url = str(first.get("html_url") or first.get("url") or "").strip()
    number = first.get("number")
    num_str = str(number).strip() if number is not None else ""
    if not url or not num_str:
        return None, None
    return url, num_str


# ---------------------------------------------------------------------------
# Merge-state + merge call
# ---------------------------------------------------------------------------


def get_pr_merge_state(
    ctx: MergeContext, pr_num: str
) -> Tuple[Optional[PrMergeStateResult], Optional[str]]:
    """Read the PR's merge-state fields via ``GET /pulls/{n}``.

    Returns ``(state, None)`` on success, ``(None, error_detail)`` on
    failure. The ``mergeStateStatus`` and ``mergeable`` REST fields are
    lowercased strings; callers compare against the lowercase canonical
    forms.
    """
    try:
        auth = resolve_auth(ctx)
    except AuthResolutionFailed as exc:
        return None, f"auth resolution failed: {exc}"
    owner, repo = gh_rest_transport.split_repo(auth.repo)
    req = RestRequest(
        method="GET",
        path=f"/repos/{owner}/{repo}/pulls/{pr_num}",
    )
    try:
        resp = request_with_retry(req, token=auth.token)
    except RestTransportError as exc:
        return None, f"pulls/{pr_num} REST read failed: {exc}"
    payload = resp.body if isinstance(resp.body, dict) else {}
    merge_state = str(payload.get("mergeable_state") or "")
    mergeable_raw = payload.get("mergeable")
    if mergeable_raw is True:
        mergeable = "true"
    elif mergeable_raw is False:
        mergeable = "false"
    elif mergeable_raw is None:
        mergeable = "unknown"
    else:
        mergeable = str(mergeable_raw).lower()
    if not merge_state or not mergeable:
        return None, (
            f"pulls/{pr_num} returned incomplete merge state: "
            f"mergeable_state={merge_state!r} mergeable={mergeable!r}"
        )
    return PrMergeStateResult(
        merge_state_status=merge_state, mergeable=mergeable
    ), None


def merge_pr(ctx: MergeContext, pr_num: str) -> PrMergeResult:
    """Merge the PR via ``PUT /pulls/{n}/merge`` with the shared retry policy.

    Returns :class:`PrMergeResult`. ``success=True`` for a merged PR,
    ``success=False`` with ``error_detail`` for terminal failures.
    """
    try:
        auth = resolve_auth(ctx)
    except AuthResolutionFailed as exc:
        return PrMergeResult(
            success=False, error_detail=f"auth resolution failed: {exc}"
        )
    owner, repo = gh_rest_transport.split_repo(auth.repo)
    req = RestRequest(
        method="PUT",
        path=f"/repos/{owner}/{repo}/pulls/{pr_num}/merge",
        body={"merge_method": "merge"},
    )
    try:
        resp = request_with_retry(req, token=auth.token)
    except RestUnprocessableError as exc:
        body_text = (exc.body or "") + " " + str(exc)
        signature = (
            "graphql-base-branch-modified"
            if "base branch was modified" in body_text.lower()
            else None
        )
        return PrMergeResult(
            success=False,
            error_detail=f"merge rejected (HTTP {exc.status}): {exc}",
            retryable_signature=signature,
        )
    except RestTransportError as exc:
        return PrMergeResult(
            success=False, error_detail=f"merge failed: {exc}"
        )
    payload = resp.body if isinstance(resp.body, dict) else {}
    if bool(payload.get("merged")):
        return PrMergeResult(success=True)
    return PrMergeResult(
        success=False,
        error_detail=(
            f"merge call returned 2xx but merged=False "
            f"(message={payload.get('message')!r})"
        ),
    )


# Re-export typed error classes so callers can import them without
# reaching into the transport module.
__all__ = (
    "AuthResolutionFailed",
    "PrCreateResult",
    "PrMergeResult",
    "PrMergeStateResult",
    "RestAuthError",
    "RestNotFoundError",
    "RestServerError",
    "RestTransportError",
    "RestUnprocessableError",
    "create_pr",
    "find_existing_pr",
    "get_pr_merge_state",
    "merge_pr",
    "resolve_auth",
    "validate_github_auth_for_merge",
)
