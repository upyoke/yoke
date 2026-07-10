"""Typed GitHub GraphQL surface.

GraphQL is the right fit for batch fetches (e.g. resync's bulk issue
status sweep) and for mutations the REST API does not expose (e.g.
``deleteIssue``). One function — :func:`graphql_query` — covers every
case; callers pass the query string and optional variables, get back
the typed JSON response dict.

Owner: re-exported from :mod:`yoke_core.domain.github_rest`.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_core.domain.gh_rest_transport import RestRequest, request_with_retry


def graphql_query(
    *,
    project: str,
    query: str,
    required_permissions: Mapping[str, str],
    variables: Optional[Mapping[str, Any]] = None,
    db_path: Optional[str] = None,
) -> Any:
    """POST /graphql.

    Returns the parsed JSON ``"data"`` field on success. Raises typed
    :class:`yoke_core.domain.gh_rest_transport.RestTransportError`
    subclasses on transport failure; raises :class:`ValueError` with
    the GraphQL ``errors`` field when the response is structurally
    valid but the query failed semantically.
    """
    from yoke_core.domain.github_rest import resolve_target

    tgt = resolve_target(
        project,
        db_path=db_path,
        required_permissions=required_permissions,
    )
    body: dict[str, Any] = {"query": query}
    if variables:
        body["variables"] = dict(variables)
    resp = request_with_retry(
        RestRequest(method="POST", path="/graphql", body=body),
        token=tgt.token,
    )
    payload = resp.body if isinstance(resp.body, dict) else {}
    if payload.get("errors"):
        raise ValueError(f"GraphQL errors: {payload['errors']}")
    return payload.get("data")


__all__ = ["graphql_query"]
