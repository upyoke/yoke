"""Runtime interface for control plane payload."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class ControlPlanePayload(Protocol):
    """Operations and values supplied by the executing adapter."""

    ControlPlanePayloadError: type[Any]
    required_field: Callable[..., Any]


def get_control_plane_payload() -> ControlPlanePayload:
    return cast(ControlPlanePayload, load_port("control_plane_payload", ControlPlanePayload))
