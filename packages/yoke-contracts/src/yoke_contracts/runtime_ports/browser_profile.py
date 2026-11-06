"""Runtime interface for browser profile."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class BrowserProfile(Protocol):
    """Operations and values supplied by the executing adapter."""

    resolve_authorized_profile: Callable[..., Any]


def get_browser_profile() -> BrowserProfile:
    return cast(BrowserProfile, load_port("browser_profile", BrowserProfile))
