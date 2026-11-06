"""Runtime interface for resilient fetch."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class ResilientFetch(Protocol):
    """Operations and values supplied by the executing adapter."""

    FetchError: type[Any]
    FetchResult: type[Any]
    fetch_bytes: Callable[..., Any]
    fetch_file: Callable[..., Any]


def get_resilient_fetch() -> ResilientFetch:
    return cast(ResilientFetch, load_port("resilient_fetch", ResilientFetch))
