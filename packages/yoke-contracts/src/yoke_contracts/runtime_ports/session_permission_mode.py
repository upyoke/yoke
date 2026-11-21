"""Runtime interface for session permission mode."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class SessionPermissionMode(Protocol):
    read_permission_mode: Callable[..., Any]


def get_session_permission_mode() -> SessionPermissionMode:
    return cast(SessionPermissionMode, load_port("session_permission_mode", SessionPermissionMode))
