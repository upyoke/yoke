"""Runtime interface for receipt."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class Receipt(Protocol):
    """Operations and values supplied by the executing adapter."""

    load_receipt: Callable[..., Any]


def get_receipt() -> Receipt:
    return cast(Receipt, load_port("receipt", Receipt))
