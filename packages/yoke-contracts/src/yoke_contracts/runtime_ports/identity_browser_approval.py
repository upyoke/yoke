"""Runtime interface for the identity-browser machine approval driver."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class IdentityBrowserApproval(Protocol):
    """Operations and values supplied by the executing adapter."""

    approve_machine_in_identity_browser: Callable[..., Any]


def get_identity_browser_approval() -> IdentityBrowserApproval:
    return cast(
        IdentityBrowserApproval,
        load_port("identity_browser_approval", IdentityBrowserApproval),
    )
