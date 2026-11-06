"""Runtime interface for deployment execution authority."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class DeploymentExecutionAuthority(Protocol):
    """Operations and values supplied by the executing adapter."""

    self_deploy_door: Callable[..., Any]


def get_deployment_execution_authority() -> DeploymentExecutionAuthority:
    return cast(DeploymentExecutionAuthority, load_port("deployment_execution_authority", DeploymentExecutionAuthority))
