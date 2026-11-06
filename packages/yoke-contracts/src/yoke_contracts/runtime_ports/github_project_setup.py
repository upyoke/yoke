"""Runtime interface for github project setup."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class GithubProjectSetup(Protocol):
    """Operations and values supplied by the executing adapter."""

    Any: Any
    GitHubProjectSetupError: type[Any]
    Path: Any
    converge: Callable[..., Any]
    destination: Any
    github_git_credentials: Any
    github_origin: Any
    github_repo_config: Any
    urlsplit: Any


def get_github_project_setup() -> GithubProjectSetup:
    return cast(GithubProjectSetup, load_port("github_project_setup", GithubProjectSetup))
