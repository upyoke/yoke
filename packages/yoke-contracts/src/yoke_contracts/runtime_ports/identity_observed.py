"""Runtime interface for identity observed."""

from __future__ import annotations

from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class IdentityObserved(Protocol):
    """Hook operations supplied by the executing adapter."""

    client_executor_version: Any
    client_machine_id: Any


def get_identity_observed() -> IdentityObserved:
    return cast(IdentityObserved, load_port("identity_observed", IdentityObserved))
