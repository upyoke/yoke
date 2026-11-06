"""Runtime interface for install advice."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class InstallAdvice(Protocol):
    """Operations and values supplied by the executing adapter."""

    install_command: Callable[..., Any]


def get_install_advice() -> InstallAdvice:
    return cast(InstallAdvice, load_port("install_advice", InstallAdvice))
