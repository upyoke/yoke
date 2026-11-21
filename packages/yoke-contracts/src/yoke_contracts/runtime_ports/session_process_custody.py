"""Runtime interface for session process custody."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class SessionProcessCustody(Protocol):
    custody_state: Callable[..., Any]


def get_session_process_custody() -> SessionProcessCustody:
    return cast(SessionProcessCustody, load_port("session_process_custody", SessionProcessCustody))
