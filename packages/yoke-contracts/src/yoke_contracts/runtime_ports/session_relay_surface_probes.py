"""Runtime interface for session relay surface probes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class SessionRelaySurfaceProbes(Protocol):
    probe_surface: Callable[..., Any]
    resolve_native_cli: Callable[..., Any]


def get_session_relay_surface_probes() -> SessionRelaySurfaceProbes:
    return cast(SessionRelaySurfaceProbes, load_port("session_relay_surface_probes", SessionRelaySurfaceProbes))
