"""Runtime interface for operating layer drift."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class OperatingLayerDrift(Protocol):
    """Operations and values supplied by the executing adapter."""

    compare_installed_layer: Callable[..., Any]
    refresh_command: Callable[..., Any]


def get_operating_layer_drift() -> OperatingLayerDrift:
    return cast(OperatingLayerDrift, load_port("operating_layer_drift", OperatingLayerDrift))
