"""Runtime interface for project onboard support."""

from __future__ import annotations

from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class ProjectOnboardSupport(Protocol):
    """Operations and values supplied by the executing adapter."""

    ProjectOnboardError: type[Any]


def get_project_onboard_support() -> ProjectOnboardSupport:
    return cast(ProjectOnboardSupport, load_port("project_onboard_support", ProjectOnboardSupport))
