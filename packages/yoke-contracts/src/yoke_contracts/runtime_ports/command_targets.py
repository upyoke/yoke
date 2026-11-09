"""Runtime interface for command targets."""

from __future__ import annotations

from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class CommandTargets(Protocol):
    """Hook operations supplied by the executing adapter."""

    ensure_handlers_loaded: Any
    item_target: Any


def get_command_targets() -> CommandTargets:
    return cast(CommandTargets, load_port("command_targets", CommandTargets))
