"""Runtime interface for pulumi stack config loader."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class PulumiStackConfigLoader(Protocol):
    """Operations and values supplied by the executing adapter."""

    load_project_renderer_settings_snapshot: Callable[..., Any]


def get_pulumi_stack_config_loader() -> PulumiStackConfigLoader:
    return cast(PulumiStackConfigLoader, load_port("pulumi_stack_config_loader", PulumiStackConfigLoader))
