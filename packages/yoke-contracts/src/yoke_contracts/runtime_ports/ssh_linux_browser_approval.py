"""Runtime interface for ssh linux browser approval."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class SshLinuxBrowserApproval(Protocol):
    """Operations and values supplied by the executing adapter."""

    approve_machine_in_desktop_chromium: Callable[..., Any]
    prepare_desktop_chromium: Callable[..., Any]


def get_ssh_linux_browser_approval() -> SshLinuxBrowserApproval:
    return cast(SshLinuxBrowserApproval, load_port("ssh_linux_browser_approval", SshLinuxBrowserApproval))
