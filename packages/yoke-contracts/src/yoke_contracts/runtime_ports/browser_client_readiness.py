"""Runtime interface for browser client readiness."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class BrowserClientReadiness(Protocol):
    """Operations and values supplied by the executing adapter."""

    DAEMON_LOG_NAME: Any
    READINESS_POLL_SECONDS: Any
    READINESS_TIMEOUT_SECONDS: Any
    launch_daemon: Callable[..., Any]
    start_daemon: Callable[..., Any]
    wait_for_daemon_ready: Callable[..., Any]


def get_browser_client_readiness() -> BrowserClientReadiness:
    return cast(BrowserClientReadiness, load_port("browser_client_readiness", BrowserClientReadiness))
