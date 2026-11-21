"""Runtime interface for machine hooks inspect."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class MachineHooksInspect(Protocol):
    STATE_INSTALLED: Any
    STATE_MALFORMED: Any
    inspect_machine_hooks: Callable[..., Any]


def get_machine_hooks_inspect() -> MachineHooksInspect:
    return cast(MachineHooksInspect, load_port("machine_hooks_inspect", MachineHooksInspect))
