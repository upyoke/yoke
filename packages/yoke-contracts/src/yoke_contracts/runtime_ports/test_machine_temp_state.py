"""Runtime interface for test machine temp state."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class TestMachineTempState(Protocol):
    """Operations and values supplied by the executing adapter."""

    require_mission_disk_space: Callable[..., Any]


def get_test_machine_temp_state() -> TestMachineTempState:
    return cast(TestMachineTempState, load_port("test_machine_temp_state", TestMachineTempState))
