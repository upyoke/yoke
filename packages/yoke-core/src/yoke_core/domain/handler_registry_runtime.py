"""Handler registration supplied by the installed service runtime."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class HandlerRegistryRuntime(Protocol):
    """Bootstrap the service's catalog without coupling domain to handlers."""

    ensure_handlers_registered: Callable[[], None]


def ensure_handlers_registered() -> None:
    """Populate the catalog on startup or first standalone dispatch."""
    runtime = cast(
        HandlerRegistryRuntime, load_port("handler_registry", HandlerRegistryRuntime)
    )
    runtime.ensure_handlers_registered()
