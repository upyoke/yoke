"""Typed GitHub REST surface — sub-issue family.

GitHub exposes parent/sub-issue relationships via the
``/repos/{owner}/{repo}/issues/{number}/sub_issues`` endpoint (preview
API). Yoke uses this to link epic-task issues to their parent epic
issue so the GitHub UI renders the hierarchy.

Owner: re-exported from :mod:`yoke_core.domain.github_rest`.
"""

from __future__ import annotations

from typing import Optional

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
)
from yoke_core.domain.gh_rest_transport import RestRequest, request_with_retry


def _target_for(
    project: str, *, required_permissions, db_path: Optional[str] = None,
):
    from yoke_core.domain.github_rest import resolve_target

    return resolve_target(
        project,
        db_path=db_path,
        required_permissions=required_permissions,
    )


def add_sub_issue(
    *, project: str, parent_number: int, child_number: int,
    db_path: Optional[str] = None,
) -> None:
    """POST /repos/{owner}/{repo}/issues/{parent}/sub_issues.

    Links ``child_number`` as a sub-issue of ``parent_number`` (both must
    exist in the same repo). The REST API requires the child's REST
    issue id (``sub_issue_id``), not the issue number, so the function
    GETs the child first to resolve it.
    """
    tgt = _target_for(
        project,
        db_path=db_path,
        required_permissions=GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
    )
    # Resolve the child's REST id (distinct from its issue number).
    child = request_with_retry(
        RestRequest(
            method="GET",
            path=f"/repos/{tgt.owner}/{tgt.repo}/issues/{child_number}",
        ),
        token=tgt.token,
    )
    body = child.body if isinstance(child.body, dict) else {}
    child_id = body.get("id")
    if not isinstance(child_id, int):
        raise ValueError(
            f"could not resolve REST id for sub-issue child "
            f"{tgt.repo_slug}#{child_number}"
        )
    request_with_retry(
        RestRequest(
            method="POST",
            path=f"/repos/{tgt.owner}/{tgt.repo}/issues/{parent_number}/sub_issues",
            body={"sub_issue_id": child_id},
        ),
        token=tgt.token,
    )


__all__ = ["add_sub_issue"]
