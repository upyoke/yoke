"""Runtime interface for hosted machine browser."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class HostedMachineBrowser(Protocol):
    """Operations and values supplied by the executing adapter."""

    open_url: Callable[..., Any]


def get_hosted_machine_browser() -> HostedMachineBrowser:
    return cast(HostedMachineBrowser, load_port("hosted_machine_browser", HostedMachineBrowser))
