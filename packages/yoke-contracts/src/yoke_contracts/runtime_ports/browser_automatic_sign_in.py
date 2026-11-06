"""Runtime interface for browser automatic sign in."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class BrowserAutomaticSignIn(Protocol):
    """Operations and values supplied by the executing adapter."""

    sign_in_entry: Callable[..., Any]


def get_browser_automatic_sign_in() -> BrowserAutomaticSignIn:
    return cast(BrowserAutomaticSignIn, load_port("browser_automatic_sign_in", BrowserAutomaticSignIn))
