"""Runtime interface for session relay termination."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class SessionRelayTermination(Protocol):
    read_local_record: Callable[..., Any]


def get_session_relay_termination() -> SessionRelayTermination:
    return cast(SessionRelayTermination, load_port("session_relay_termination", SessionRelayTermination))
