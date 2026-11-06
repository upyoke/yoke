"""Runtime interface for writer."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class MachineConfigWrites(Protocol):
    """Operations and values supplied by the executing adapter."""

    MachineConfigWriteError: Any
    clear_github: Any
    register_project: Any
    remove_connection: Any
    remove_connections: Any
    set_active_env: Callable[..., Any]
    set_connection: Callable[..., Any]
    set_credential: Callable[..., Any]
    set_github: Any
    set_runtime_paths: Callable[..., Any]


def get_machine_config_writes() -> MachineConfigWrites:
    return cast(MachineConfigWrites, load_port("machine_config_writes", MachineConfigWrites))
