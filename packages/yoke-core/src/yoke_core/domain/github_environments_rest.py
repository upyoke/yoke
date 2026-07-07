"""GitHub deployment environment configuration via REST.

Replaces the former host-CLI environment provisioning shellout used by
bootstrap_project_setup when provisioning the ``production``
deployment environment. Returns the parsed environment row on success;
raises a typed :class:`RestTransportError` subclass on failure.

The same endpoint covers both initial creation and update — a PUT with
no body creates a default environment, a PUT with the protection-rule
JSON applies those rules. ``put_environment`` accepts an optional
``config`` dict; pass ``None`` for the basic default.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_core.domain.gh_rest_transport import (
    RestRequest,
    RestTransportError,
    request_with_retry,
)


def put_environment(
    repo: str,
    name: str,
    *,
    token: str,
    config: Optional[Mapping[str, Any]] = None,
) -> Mapping[str, Any]:
    """Create or update a deployment environment.

    ``config`` is the protection-rule JSON body GitHub accepts on this
    endpoint (e.g. ``{"reviewers": [...], "deployment_branch_policy": ...}``).
    Pass ``None`` (the default) to create a minimal environment with no
    protection rules.
    """
    req = RestRequest(
        method="PUT",
        path=f"/repos/{repo}/environments/{name}",
        body=dict(config) if config else {},
    )
    resp = request_with_retry(req, token=token)
    return resp.body if isinstance(resp.body, Mapping) else {}


def fetch_authenticated_user(*, token: str) -> Mapping[str, Any]:
    """Return the GitHub user record for the PAT-authenticated principal.

    Used by bootstrap_project_setup to resolve the operator's login and
    numeric ID for the ``reviewers`` deployment-protection rule.
    """
    req = RestRequest(method="GET", path="/user")
    resp = request_with_retry(req, token=token)
    return resp.body if isinstance(resp.body, Mapping) else {}


__all__ = [
    "fetch_authenticated_user",
    "put_environment",
]
