"""Runtime interface for identity relay."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class IdentityRelay(Protocol):
    """Operations and values supplied by the executing adapter."""

    client_entrypoint: Callable[..., Any]
    resolve_model_facts: Any


def get_identity_relay() -> IdentityRelay:
    return cast(IdentityRelay, load_port("identity_relay", IdentityRelay))
