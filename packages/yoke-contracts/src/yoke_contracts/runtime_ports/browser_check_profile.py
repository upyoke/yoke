"""Runtime interface for browser check profile."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class BrowserCheckProfile(Protocol):
    """Operations and values supplied by the executing adapter."""

    check_scope: Callable[..., Any]
    record_daemon_owner: Callable[..., Any]


def get_browser_check_profile() -> BrowserCheckProfile:
    return cast(BrowserCheckProfile, load_port("browser_check_profile", BrowserCheckProfile))
