"""Merge-engine PR REST helpers.

Direct REST calls through :mod:`yoke_core.domain.gh_rest_transport` handle
the merge engine's pull-request operations. Canonical auth resolves once per
helper invocation; there is no second secret-storage shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_CONTENTS_WRITE_PERMISSION_LEVELS as CONTENTS_WRITE,
    GITHUB_PULL_REQUESTS_READ_PERMISSION_LEVELS as PR_READ,
    GITHUB_PULL_REQUESTS_WRITE_PERMISSION_LEVELS as PR_WRITE,
)

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
from yoke_core.domain.merge_github_authority import MergeAuthority
from yoke_core.domain.project_github_auth import (
    GITHUB_AUTHORITY_USER,
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
    # GitHub refuses a pull request whose head adds nothing to the base. For
    # a branch that was about to be merged, that refusal says the branch has
    # already landed, so callers converge on the landed state rather than
    # reporting the refusal as a failed merge.
    no_commits: bool = False
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


def resolve_auth(
    ctx: MergeContext,
    *,
    required_permissions: Mapping[str, str],
    required_authority: str = GITHUB_AUTHORITY_USER,
) -> ProjectGithubAuth:
    """Resolve the project's GitHub auth bundle for this merge.

    ``required_authority`` is the weakest authority that can perform the
    operation, so a read the installation is authorized to serve is not
    refused for want of a machine user authorization.

    Raises :class:`AuthResolutionFailed` carrying a repair hint when the
    project capability / secret / repo metadata is incomplete.
    """
    project = ctx.project or ""
    if not project or project == "null":
        raise AuthResolutionFailed(
            "merge context has no project; REST transport requires project auth"
        )
    try:
        return resolve_project_github_auth(
            project,
            required_permissions=required_permissions,
            required_authority=required_authority,
        )
    except ProjectGithubAuthError as exc:
        hint = repair_command_hint(exc, project)
        raise AuthResolutionFailed(
            f"{exc.code}: {exc}", hint=hint
        ) from exc


def validate_github_auth_for_merge(
    ctx: MergeContext, authority: MergeAuthority,
) -> Tuple[bool, Optional[str]]:
    """Admit one merge route against the authority it was classified as needing.

    ``merge_worktree_runner.run`` calls this before any merge work, so a route
    whose authority cannot be resolved is refused while the branch is still
    unlanded. Returns ``(True, None)`` when the resolver succeeds and the
    bearer token is non-empty, and ``(False, message)`` otherwise, with the
    classification and the repair hint already in the message so the operator
    can see which authority the refusal was about.
    """
    try:
        auth = resolve_auth(
            ctx,
            required_permissions=authority.permissions,
            required_authority=authority.authority,
        )
    except AuthResolutionFailed as exc:
        message = f"Error: {exc}\n  Requires: {authority.describe()}"
        if exc.hint:
            message = f"{message}\n  Repair: {exc.hint}"
        return False, message
    if not auth.token:
        return False, (
            f"Error: project '{ctx.project}' resolved an empty GitHub bearer token "
            f"for {authority.describe()}; reconnect the GitHub App installation "
            "or refresh the repo binding"
        )
    return True, None


# ---------------------------------------------------------------------------
# PR create
# ---------------------------------------------------------------------------


def create_pr(
    ctx: MergeContext,
    *,
    title: str,
    body: str,
) -> PrCreateResult:
    """Create a pull request via REST.

    Returns :class:`PrCreateResult` with ``pr_url``/``pr_num`` populated on
    success, ``already_exists=True`` when GitHub returns 422 with the
    documented "A pull request already exists" message, or
    ``no_commits=True`` when it returns 422 because the head adds nothing to
    the base. Hard failures return with ``error_detail`` populated and
    ``pr_url``/``pr_num`` empty.
    """
    auth = resolve_auth(ctx, required_permissions=PR_WRITE)
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
        if "no commits between" in lowered:
            return PrCreateResult(pr_url="", pr_num="", no_commits=True)
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
        auth = resolve_auth(ctx, required_permissions=PR_READ)
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
        auth = resolve_auth(ctx, required_permissions=CONTENTS_WRITE)
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
    "get_pr_merge_state",
    "merge_pr",
    "resolve_auth",
    "validate_github_auth_for_merge",
)
