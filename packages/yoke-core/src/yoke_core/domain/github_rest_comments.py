"""Typed GitHub REST surface — issue comment family.

Owner: re-exported from :mod:`yoke_core.domain.github_rest`.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.gh_rest_transport import RestRequest, request_with_retry


def _parse_comment(payload: Any):
    """Parse a single GitHub /issues/{n}/comments payload into Comment."""
    from yoke_core.domain.github_rest import Comment

    if not isinstance(payload, dict):
        raise ValueError(
            f"unexpected GitHub comment payload shape: {type(payload).__name__}"
        )
    user = payload.get("user") or {}
    user_login = str(user.get("login", "")) if isinstance(user, dict) else ""
    return Comment(
        id=int(payload.get("id", 0)),
        body=str(payload.get("body") or ""),
        html_url=str(payload.get("html_url", "")),
        user_login=user_login,
    )


def _target_for(project: str, *, db_path: Optional[str] = None):
    from yoke_core.domain.github_rest import resolve_target

    return resolve_target(project, db_path=db_path)


def _transport_budget_kwargs(
    timeout_seconds: Optional[float], max_attempts: Optional[int],
) -> dict[str, object]:
    pairs = (("timeout_seconds", timeout_seconds), ("max_attempts", max_attempts))
    return {name: value for name, value in pairs if value is not None}


def post_comment(
    *, project: str, number: int, body: str,
    db_path: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
    max_attempts: Optional[int] = None,
):
    """POST /repos/{owner}/{repo}/issues/{number}/comments."""
    tgt = _target_for(project, db_path=db_path)
    resp = request_with_retry(
        RestRequest(
            method="POST",
            path=f"/repos/{tgt.owner}/{tgt.repo}/issues/{number}/comments",
            body={"body": body},
        ),
        token=tgt.token,
        **_transport_budget_kwargs(timeout_seconds, max_attempts),
    )
    return _parse_comment(resp.body)


def list_comments(
    *, project: str, number: int, limit: int = 100,
    db_path: Optional[str] = None,
) -> list:
    """GET /repos/{owner}/{repo}/issues/{number}/comments. Returns list of Comment."""
    tgt = _target_for(project, db_path=db_path)
    items: list[Any] = []
    page = 1
    per_page = min(100, max(1, limit))
    while len(items) < limit:
        resp = request_with_retry(
            RestRequest(
                method="GET",
                path=f"/repos/{tgt.owner}/{tgt.repo}/issues/{number}/comments",
                query={"per_page": str(per_page), "page": str(page)},
            ),
            token=tgt.token,
        )
        batch = resp.body if isinstance(resp.body, list) else []
        if not batch:
            break
        items.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
    items = items[:limit]
    return [_parse_comment(item) for item in items if isinstance(item, dict)]


__all__ = ["post_comment", "list_comments"]
