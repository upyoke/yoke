"""Context-local GitHub App user authorization for local dispatch."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Callable

from yoke_contracts.github_origin import GitHubApiEndpoint


LOCAL_USER_TOKEN_PROVIDER: ContextVar[Callable[[], str] | None] = ContextVar(
    "project_github_local_user_token_provider",
    default=None,
)
LOCAL_API_ENDPOINT: ContextVar[GitHubApiEndpoint | None] = ContextVar(
    "project_github_local_api_endpoint",
    default=None,
)


__all__ = ["LOCAL_API_ENDPOINT", "LOCAL_USER_TOKEN_PROVIDER"]
