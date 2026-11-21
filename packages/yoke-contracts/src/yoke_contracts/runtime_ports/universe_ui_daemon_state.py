"""Runtime interface for reading the machine's local UI daemon."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class UniverseUiDaemonState(Protocol):
    read_record: Callable[..., Any]
    process_alive: Callable[..., Any]


def get_universe_ui_daemon_state() -> UniverseUiDaemonState:
    return cast(
        UniverseUiDaemonState, load_port("universe_ui_daemon_state", UniverseUiDaemonState)
    )
