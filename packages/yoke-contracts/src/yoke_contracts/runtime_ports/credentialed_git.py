"""Runtime interface for credentialed git."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class CredentialedGit(Protocol):
    """Operations and values supplied by the executing adapter."""

    CredentialedGitError: type[Any]
    RECONNECT_RECOVERY: Any
    REFUSAL_EXIT_CODE: Any
    TIMEOUT_EXIT_CODE: Any
    TRANSIENT_RECOVERY: Any
    configured_web_url: Callable[..., Any]
    credentialed_github_env: Callable[..., Any]
    git_environment: Callable[..., Any]
    is_configured_github: Callable[..., Any]
    resolve_token: Callable[..., Any]
    run: Callable[..., Any]


def get_credentialed_git() -> CredentialedGit:
    return cast(CredentialedGit, load_port("credentialed_git", CredentialedGit))
