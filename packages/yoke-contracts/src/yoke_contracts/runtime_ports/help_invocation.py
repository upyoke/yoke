"""Runtime interface for help invocation."""

from __future__ import annotations

from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class HelpInvocation(Protocol):
    """Hook operations supplied by the executing adapter."""

    is_help_only_command: Any


def get_help_invocation() -> HelpInvocation:
    return cast(HelpInvocation, load_port("help_invocation", HelpInvocation))
