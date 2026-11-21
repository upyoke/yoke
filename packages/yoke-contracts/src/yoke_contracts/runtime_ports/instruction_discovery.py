"""Runtime interface for instruction discovery."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class InstructionDiscovery(Protocol):
    preflight: Callable[..., Any]


def get_instruction_discovery() -> InstructionDiscovery:
    return cast(InstructionDiscovery, load_port("instruction_discovery", InstructionDiscovery))
