"""Runtime interface for git hooks."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class ProjectInstallGitHooks(Protocol):
    """Operations and values supplied by the executing adapter."""

    BootstrapResult: type[Any]
    GIT_HOOK_NAMES: Any
    install_git_hooks: Callable[..., Any]


def get_project_install_git_hooks() -> ProjectInstallGitHooks:
    return cast(ProjectInstallGitHooks, load_port("project_install_git_hooks", ProjectInstallGitHooks))
