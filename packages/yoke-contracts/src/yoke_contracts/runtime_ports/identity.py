"""Runtime interface for identity."""

from __future__ import annotations

from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class Identity(Protocol):
    """Operations and values supplied by the executing adapter."""

    canonical_harness_id: Any
    compose_executor_from_entrypoint: Any
    detect_executor: Any
    cursor_surface_entrypoint: Any


def get_identity() -> Identity:
    return cast(Identity, load_port("identity", Identity))
