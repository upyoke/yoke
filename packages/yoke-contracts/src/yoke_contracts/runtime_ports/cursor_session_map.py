"""Runtime interface for cursor session map."""

from __future__ import annotations

from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class CursorSessionMap(Protocol):
    """Hook operations supplied by the executing adapter."""

    record_conversation_session: Any


def get_cursor_session_map() -> CursorSessionMap:
    return cast(CursorSessionMap, load_port("cursor_session_map", CursorSessionMap))
