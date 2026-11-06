"""Runtime interface for runner."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class ProjectInstallation(Protocol):
    """Operations and values supplied by the executing adapter."""

    MODE_COPY: Any
    MODE_KEY: Any
    MODE_SOURCE_LINK: Any
    ProjectInstallError: Any
    apply_bundle: Any
    install: Callable[..., Any]
    refresh: Callable[..., Any]
    uninstall: Any


def get_project_installation() -> ProjectInstallation:
    return cast(ProjectInstallation, load_port("project_installation", ProjectInstallation))
