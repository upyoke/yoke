"""Runtime interface for https."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class Https(Protocol):
    """Operations and values supplied by the executing adapter."""

    HttpsConnection: type[Any]
    ServerHandshake: Any
    TransportError: Any
    relay_https: Callable[..., Any]
    resolve_https_connection: Callable[..., Any]


def get_https() -> Https:
    return cast(Https, load_port("https", Https))
