"""Runtime interface for dispatcher."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class Dispatcher(Protocol):
    """Operations and values supplied by the executing adapter."""

    build_request: Callable[..., Any]


def get_dispatcher() -> Dispatcher:
    return cast(Dispatcher, load_port("dispatcher", Dispatcher))
