"""Runtime interface for browser human gate."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class BrowserHumanGate(Protocol):
    """Operations and values supplied by the executing adapter."""

    refuse_during_human_gate: Callable[..., Any]


def get_browser_human_gate() -> BrowserHumanGate:
    return cast(BrowserHumanGate, load_port("browser_human_gate", BrowserHumanGate))
