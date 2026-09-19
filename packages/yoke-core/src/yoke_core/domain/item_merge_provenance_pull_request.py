"""Operator repair of which pull request carried an item's landing.

``items.merge_queue_pr_number`` names the pull request every later landing
question is asked of: the merge-group receipt, the control-plane landing
observation, and close-out. It is a marker rather than frozen provenance, so
it can legitimately be repointed -- and it has to be, because a lane whose
commits reach the base under a sibling pull request leaves its own one open
forever, and every retry then asks that open pull request about a merge it
never performed.

The repair is verified, not asserted: GitHub must report the named pull
request merged, on this project's own repository. Its predecessor's queue
admission, landing stamp and observation row are dropped with the number
they belonged to, through the shared marker writer the merge boundary uses.

Human-only, reason-required, ledger-first — the same accountability the
merged_at correction carries, from
:mod:`yoke_core.domain.item_merge_provenance_operator`.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from yoke_core.domain.item_merge_provenance_operator import (
    MergedAtCorrectionError,
    emit_correction,
    sql_placeholder,
    require_human_context,
    row_value,
)
from yoke_core.domain.project_identity import render_item_ref
from yoke_contracts.public_ref import ITEM_NOT_FOUND

LANDING_PULL_REQUEST_CORRECTION_EVENT = "OperatorLandingPullRequestCorrection"


def operator_correct_landing_pull_request(
    conn: Any,
    item_id: int,
    pr_number: str,
    operator_reason: str,
    *,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Repoint an item at the pull request that actually merged its work.

    The recorded carrier is a marker, not frozen provenance: an item can end
    up pointing at a pull request that never merged, while a sibling one
    carried its commits in. Every later question — the merge-group receipt,
    the landing observation, close-out — then asks the wrong pull request
    and gets a correct "this never merged" back.

    So the replacement is verified rather than asserted: GitHub must report
    it merged, on this project's own repository. Its predecessor's queue and
    landing stamps go with the number they belonged to.
    """
    require_human_context("Landing pull-request correction")
    if not operator_reason or not operator_reason.strip():
        raise MergedAtCorrectionError("operator_reason must be a non-empty string")
    replacement = str(pr_number or "").strip().lstrip("#")
    if not replacement.isdigit():
        raise MergedAtCorrectionError(
            f"pr_number must be a pull request number; got {pr_number!r}"
        )
    public_ref = render_item_ref(conn, int(item_id))
    merge_sha, merged_at = _verify_merged_pull_request(conn, item_id, replacement)
    from yoke_core.domain.merge_queue_landing_marker import (
        point_item_at_pull_request,
        read_landing_marker,
    )

    previous = read_landing_marker(conn, int(item_id))
    if previous is None:
        raise MergedAtCorrectionError(ITEM_NOT_FOUND)
    context = {
        "item_id": int(item_id),
        "public_ref": public_ref,
        "previous_pr_number": previous["pr_number"],
        "pr_number": replacement,
        "merge_commit_sha": merge_sha,
        "merged_at": merged_at,
        "operator_reason": operator_reason,
    }
    emit_correction(
        LANDING_PULL_REQUEST_CORRECTION_EVENT,
        session_id=session_id or "",
        item_id=int(item_id),
        context=context,
    )
    marker = point_item_at_pull_request(conn, int(item_id), replacement)
    return {
        "corrected": True,
        "item_id": int(item_id),
        "public_ref": public_ref,
        "previous_pr_number": previous["pr_number"],
        "pr_number": replacement,
        "merge_commit_sha": merge_sha,
        "merged_at": merged_at,
        "operator_reason": operator_reason,
        "operator_session_id": session_id or "",
        "landing_marker": marker or {},
    }


def _verify_merged_pull_request(
    conn: Any, item_id: int, pr_number: str
) -> tuple[str, str]:
    """Return the pull request's merge commit and time, or refuse by name."""
    from yoke_core.domain.gh_rest_transport import (
        RestRequest,
        request_with_retry,
        split_repo,
    )
    from yoke_core.domain.gh_rest_transport_errors import RestTransportError
    from yoke_contracts.github_app_installation_permissions import (
        GITHUB_PULL_REQUESTS_READ_PERMISSION_LEVELS,
    )
    from yoke_core.domain.project_github_auth import (
        ProjectGithubAuthError,
        resolve_project_github_auth,
    )
    from yoke_core.domain.project_identity import resolve_project_slug

    placeholder = sql_placeholder(conn)
    row = conn.execute(
        f"SELECT project_id FROM items WHERE id = {placeholder}",
        (int(item_id),),
    ).fetchone()
    if row is None:
        raise MergedAtCorrectionError(ITEM_NOT_FOUND)
    slug = resolve_project_slug(conn, int(row_value(row, "project_id", 0)))
    try:
        auth = resolve_project_github_auth(
            slug,
            conn=conn,
            required_permissions=GITHUB_PULL_REQUESTS_READ_PERMISSION_LEVELS,
        )
    except ProjectGithubAuthError as exc:
        raise MergedAtCorrectionError(
            f"this correction is verified against GitHub, and {slug}'s "
            f"binding could not be read: {exc}"
        ) from exc
    owner, repo = split_repo(auth.repo)
    try:
        response = request_with_retry(
            RestRequest(method="GET", path=f"/repos/{owner}/{repo}/pulls/{pr_number}"),
            token=auth.token,
        )
    except RestTransportError as exc:
        raise MergedAtCorrectionError(
            f"pull request {pr_number} could not be read from {auth.repo}: "
            f"{exc}. The correction is verified, never asserted; retry once "
            "the provider is reachable."
        ) from exc
    body = response.body if isinstance(response.body, dict) else {}
    # An open pull request still reports a merge_commit_sha -- GitHub's own
    # test-merge -- so the merged flag is what says this one landed.
    if not bool(body.get("merged") or body.get("merged_at")):
        raise MergedAtCorrectionError(
            f"pull request {pr_number} on {auth.repo} has not merged, so it "
            "cannot be the carrier of this item's landing. Name the pull "
            "request whose merge the base actually holds."
        )
    return (
        str(body.get("merge_commit_sha") or ""),
        str(body.get("merged_at") or ""),
    )


__all__ = [
    "LANDING_PULL_REQUEST_CORRECTION_EVENT",
    "operator_correct_landing_pull_request",
]
