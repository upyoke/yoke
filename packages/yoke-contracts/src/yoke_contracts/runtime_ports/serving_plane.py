"""Runtime interface for serving plane."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class ServingPlane(Protocol):
    """Operations and values supplied by the executing adapter."""

    ServingControlPlaneUnresolved: type[Any]
    serving_control_plane_env: Callable[..., Any]


def get_serving_plane() -> ServingPlane:
    return cast(ServingPlane, load_port("serving_plane", ServingPlane))
