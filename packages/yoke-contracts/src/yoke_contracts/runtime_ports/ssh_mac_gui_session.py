"""Runtime interface for ssh mac gui session."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class SshMacGuiSession(Protocol):
    """Operations and values supplied by the executing adapter."""

    classify_macos_session_context_failure: Callable[..., Any]


def get_ssh_mac_gui_session() -> SshMacGuiSession:
    return cast(SshMacGuiSession, load_port("ssh_mac_gui_session", SshMacGuiSession))
