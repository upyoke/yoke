"""Runtime interface for onboard project github inputs."""

from __future__ import annotations

from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class OnboardProjectGithubInputs(Protocol):
    """Operations and values supplied by the executing adapter."""

    MachineGitHubInputError: type[Any]


def get_onboard_project_github_inputs() -> OnboardProjectGithubInputs:
    return cast(OnboardProjectGithubInputs, load_port("onboard_project_github_inputs", OnboardProjectGithubInputs))
