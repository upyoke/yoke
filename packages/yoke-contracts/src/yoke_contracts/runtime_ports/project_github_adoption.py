"""Runtime interface for project github adoption."""

from __future__ import annotations

from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class ProjectGithubAdoption(Protocol):
    """Operations and values supplied by the executing adapter."""

    ProjectGithubAdoptionError: type[Any]


def get_project_github_adoption() -> ProjectGithubAdoption:
    return cast(ProjectGithubAdoption, load_port("project_github_adoption", ProjectGithubAdoption))
