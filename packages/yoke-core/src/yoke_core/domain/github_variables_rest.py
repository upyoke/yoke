"""GitHub Actions repo variables — set via bearer-token REST (upsert).

Sibling of :mod:`yoke_core.domain.github_secrets_rest`: secrets need
libsodium sealed-box encryption, repo variables are plaintext
name/value pairs with separate create/update REST verbs. GitHub has no
single upsert endpoint for variables, so :func:`set_repo_variable`
PATCHes the existing variable first (the common rotation / disarm
case) and falls back to POST-create when the PATCH 404s.

Token resolution flows through ``resolve_project_github_auth`` at the
caller — never through host GitHub CLI credentials.
"""

from __future__ import annotations

from yoke_core.domain.gh_rest_transport import (
    RestNotFoundError,
    RestRequest,
    request_with_retry,
)


def set_repo_variable(repo: str, name: str, value: str, *, token: str) -> str:
    """Create or update the Actions variable ``name`` on ``repo``.

    Returns ``"updated"`` when the existing variable was PATCHed and
    ``"created"`` when the 404 fallback POSTed a new one. Raises
    :class:`yoke_core.domain.gh_rest_transport.RestTransportError`
    (or a subclass) on terminal failure.
    """
    body = {"name": name, "value": value}
    patch = RestRequest(
        method="PATCH",
        replay_safe=True,
        path=f"/repos/{repo}/actions/variables/{name}",
        body=body,
    )
    try:
        request_with_retry(patch, token=token)
        return "updated"
    except RestNotFoundError:
        pass
    post = RestRequest(
        method="POST",
        path=f"/repos/{repo}/actions/variables",
        body=body,
    )
    request_with_retry(post, token=token)
    return "created"


def get_repo_variable(repo: str, name: str, *, token: str):
    """Return the Actions variable ``name`` on ``repo``, or ``None`` when absent.

    Read-only diagnosability sibling of :func:`set_repo_variable` — lets
    operators confirm arming-gate state (e.g. a workflow job that
    self-skipped on a ``vars`` condition) without mutating repo config.
    """
    get = RestRequest(
        method="GET",
        path=f"/repos/{repo}/actions/variables/{name}",
    )
    try:
        response = request_with_retry(get, token=token)
    except RestNotFoundError:
        return None
    body = response.body if isinstance(response.body, dict) else {}
    value = body.get("value")
    return value if isinstance(value, str) else None


__all__ = ["get_repo_variable", "set_repo_variable"]
