"""Runtime interface for diagnosing and repairing the login-shell launcher PATH."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class LauncherPathDoctor(Protocol):
    """Operations supplied by the executing adapter."""

    diagnose: Callable[..., Any]
    update_shell: Callable[..., Any]


def get_launcher_path_doctor() -> LauncherPathDoctor:
    return cast(
        LauncherPathDoctor, load_port("launcher_path_doctor", LauncherPathDoctor)
    )
