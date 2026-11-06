"""Runtime interface for session liveness."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class SessionLiveness(Protocol):
    """Operations and values supplied by the executing adapter."""

    contender_is_live: Callable[..., Any]


def get_session_liveness() -> SessionLiveness:
    return cast(SessionLiveness, load_port("session_liveness", SessionLiveness))
