"""Runtime interface for project git prerequisite."""

from __future__ import annotations

from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class ProjectGitPrerequisite(Protocol):
    """Operations and values supplied by the executing adapter."""

    MissingGitError: type[Any]


def get_project_git_prerequisite() -> ProjectGitPrerequisite:
    return cast(ProjectGitPrerequisite, load_port("project_git_prerequisite", ProjectGitPrerequisite))
