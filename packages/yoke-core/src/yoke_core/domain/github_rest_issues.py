"""Typed GitHub REST surface — issue family.

Every issue mutation routes through one of these typed functions. None of
them accept argv-shaped lists; all kwargs are typed. All responses are
parsed into typed :class:`yoke_core.domain.github_rest.Issue`
dataclasses (or ``None`` for explicit 404). Transport errors propagate
as typed exception classes from
:mod:`yoke_core.domain.gh_rest_transport`:

- :class:`RestNotFoundError` (404) — issue does not exist in this repo
- :class:`RateLimitedError` (429 or 403 with rate-limit body) — retry
  policy in :mod:`gh_rest_transport` already applied; caller can defer.
- :class:`RestAuthError` (401, non-rate-limit 403) — token missing or
  lacks scope; caller surfaces as permission diagnostic.
- :class:`RestUnprocessableError` (422) — semantic rejection.
- :class:`RestServerError` (5xx) — transient after retry budget.

Owner: re-exported from :mod:`yoke_core.domain.github_rest`.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence

from yoke_core.domain.gh_rest_transport import (
    RestNotFoundError,
    RestRequest,
    request_with_retry,
)


def _parse_issue(payload: Any):
    """Parse a single GitHub /issues REST payload into an Issue dataclass."""
    from yoke_core.domain.github_rest import Issue

    if not isinstance(payload, dict):
        raise ValueError(f"unexpected GitHub issue payload shape: {type(payload).__name__}")
    labels_raw = payload.get("labels") or []
    label_names: list[str] = []
    for lab in labels_raw:
        if isinstance(lab, dict) and lab.get("name") is not None:
            label_names.append(str(lab["name"]))
    user = payload.get("user") or {}
    user_login = str(user.get("login", "")) if isinstance(user, dict) else ""
    return Issue(
        number=int(payload.get("number", 0)),
        title=str(payload.get("title", "")),
        state=str(payload.get("state", "")).upper(),
        body=str(payload.get("body") or ""),
        labels=tuple(label_names),
        html_url=str(payload.get("html_url", "")),
        user_login=user_login,
    )


def _target_for(project: str, *, db_path: Optional[str] = None):
    """Resolve the typed REST target — small wrapper so call sites stay tight."""
    from yoke_core.domain.github_rest import resolve_target

    return resolve_target(project, db_path=db_path)


def create_issue(
    *, project: str, title: str, body: str = "",
    labels: Sequence[str] = (), db_path: Optional[str] = None,
):
    """POST /repos/{owner}/{repo}/issues. Returns the typed Issue."""
    tgt = _target_for(project, db_path=db_path)
    payload: dict[str, Any] = {"title": title, "body": body}
    if labels:
        payload["labels"] = list(labels)
    resp = request_with_retry(
        RestRequest(
            method="POST", path=f"/repos/{tgt.owner}/{tgt.repo}/issues",
            body=payload,
        ),
        token=tgt.token,
    )
    return _parse_issue(resp.body)


def update_issue(
    *, project: str, number: int, title: Optional[str] = None,
    body: Optional[str] = None, db_path: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
    max_attempts: Optional[int] = None,
):
    """PATCH /repos/{owner}/{repo}/issues/{number} for title/body fields.

    Pass ``None`` for fields you don't want to change. Returns the
    updated Issue.
    """
    tgt = _target_for(project, db_path=db_path)
    patch: dict[str, Any] = {}
    if title is not None:
        patch["title"] = title
    if body is not None:
        patch["body"] = body
    if not patch:
        return get_issue(project=project, number=number, db_path=db_path)
    resp = request_with_retry(
        RestRequest(
            method="PATCH",
            path=f"/repos/{tgt.owner}/{tgt.repo}/issues/{number}",
            body=patch,
        ),
        token=tgt.token,
        **_transport_budget_kwargs(timeout_seconds, max_attempts),
    )
    return _parse_issue(resp.body)


def set_issue_state(
    *, project: str, number: int, state: str,
    comment: Optional[str] = None, db_path: Optional[str] = None,
):
    """PATCH issue state to ``"open"`` or ``"closed"``.

    When ``comment`` is given, posts the comment first via
    :func:`yoke_core.domain.github_rest_comments.post_comment` so the
    state change carries a human-readable rationale.
    """
    if state not in ("open", "closed"):
        raise ValueError(f"state must be 'open' or 'closed', got: {state!r}")
    tgt = _target_for(project, db_path=db_path)
    if comment:
        # Lazy import to avoid umbrella-init circular binding.
        from yoke_core.domain.github_rest_comments import post_comment
        post_comment(project=project, number=number, body=comment, db_path=db_path)
    resp = request_with_retry(
        RestRequest(
            method="PATCH",
            path=f"/repos/{tgt.owner}/{tgt.repo}/issues/{number}",
            body={"state": state},
        ),
        token=tgt.token,
    )
    return _parse_issue(resp.body)


def get_issue(
    *, project: str, number: int, db_path: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
    max_attempts: Optional[int] = None,
):
    """GET /repos/{owner}/{repo}/issues/{number}.

    Returns the typed Issue, or ``None`` when the issue does not exist
    in this repo (HTTP 404). Other transport errors propagate as their
    typed exception classes — callers like ``_validate_issue_in_repo``
    inspect the exception to distinguish rate-limit / permission /
    transient from "actually absent."
    """
    tgt = _target_for(project, db_path=db_path)
    try:
        resp = request_with_retry(
            RestRequest(
                method="GET",
                path=f"/repos/{tgt.owner}/{tgt.repo}/issues/{number}",
            ),
            token=tgt.token,
            **_transport_budget_kwargs(timeout_seconds, max_attempts),
        )
    except RestNotFoundError:
        return None
    return _parse_issue(resp.body)


def _transport_budget_kwargs(
    timeout_seconds: Optional[float], max_attempts: Optional[int],
) -> dict[str, object]:
    kwargs: dict[str, object] = {}
    if timeout_seconds is not None:
        kwargs["timeout_seconds"] = timeout_seconds
    if max_attempts is not None:
        kwargs["max_attempts"] = max_attempts
    return kwargs


def list_issues(
    *, project: str, state: str = "all", label: str = "",
    search: str = "", limit: int = 100, db_path: Optional[str] = None,
):
    """GET /repos/{owner}/{repo}/issues or /search/issues.

    When ``search`` is non-empty, dispatches to the Search API
    (``GET /search/issues``) with the project repo scope; otherwise
    the issues list endpoint. Returns a list of typed Issue.
    """
    tgt = _target_for(project, db_path=db_path)
    items: list[Any] = []
    if search:
        query = f"repo:{tgt.owner}/{tgt.repo} {search}"
        if label:
            query += f' label:"{label}"'
        page = 1
        per_page = min(100, max(1, limit))
        while len(items) < limit:
            resp = request_with_retry(
                RestRequest(
                    method="GET", path="/search/issues",
                    query={"q": query, "per_page": str(per_page), "page": str(page)},
                ),
                token=tgt.token,
            )
            body = resp.body if isinstance(resp.body, dict) else {}
            batch = body.get("items") or []
            if not batch:
                break
            items.extend(batch)
            if len(batch) < per_page:
                break
            page += 1
        items = items[:limit]
    else:
        page = 1
        per_page = min(100, max(1, limit))
        while len(items) < limit:
            query_args: dict[str, str] = {
                "state": state, "per_page": str(per_page), "page": str(page),
            }
            if label:
                query_args["labels"] = label
            resp = request_with_retry(
                RestRequest(
                    method="GET",
                    path=f"/repos/{tgt.owner}/{tgt.repo}/issues",
                    query=query_args,
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
    return [_parse_issue(item) for item in items if isinstance(item, dict)]


def delete_issue(
    *, project: str, number: int, db_path: Optional[str] = None,
) -> None:
    """DELETE an issue via the GraphQL mutation (REST has no delete endpoint).

    The REST API does not expose a direct delete; GitHub requires the
    GraphQL ``deleteIssue`` mutation. Routes through
    :func:`yoke_core.domain.github_rest_graphql.graphql_query`.
    """
    from yoke_core.domain.github_rest_graphql import graphql_query

    tgt = _target_for(project, db_path=db_path)
    # First resolve the issue's node_id via REST (deleteIssue needs it).
    resp = request_with_retry(
        RestRequest(
            method="GET",
            path=f"/repos/{tgt.owner}/{tgt.repo}/issues/{number}",
        ),
        token=tgt.token,
    )
    payload = resp.body if isinstance(resp.body, dict) else {}
    node_id = str(payload.get("node_id", ""))
    if not node_id:
        raise ValueError(f"issue {tgt.repo_slug}#{number} has no node_id")
    graphql_query(
        project=project,
        query="mutation($id: ID!) { deleteIssue(input: {issueId: $id}) { repository { id } } }",
        variables={"id": node_id},
        db_path=db_path,
    )
