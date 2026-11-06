"""Runtime interface for project git bootstrap."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class ProjectGitBootstrap(Protocol):
    """Operations and values supplied by the executing adapter."""

    bootstrap_checkout: Callable[..., Any]


def get_project_git_bootstrap() -> ProjectGitBootstrap:
    return cast(ProjectGitBootstrap, load_port("project_git_bootstrap", ProjectGitBootstrap))
