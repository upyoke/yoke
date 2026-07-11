"""Test-only transport seam for loopback project-onboarding API fixtures."""

from __future__ import annotations

import threading
from typing import Any

from yoke_cli.transport import https as https_transport
from yoke_cli.transport.https_urlopen import open_no_redirect


def enable_local_http_function_relay() -> Any:
    """Route the relay through its injectable opener so HTTP fixtures work."""
    original = https_transport.open_no_redirect

    def open_local_relay(request, timeout):
        return open_no_redirect(request, timeout=timeout)

    https_transport.open_no_redirect = open_local_relay
    return original


def restore_function_relay_opener(opener: Any) -> None:
    https_transport.open_no_redirect = opener


def start_server_thread(server: Any) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


__all__ = [
    "enable_local_http_function_relay",
    "restore_function_relay_opener",
    "start_server_thread",
]
