"""Runtime port for Cursor orientation payload parsing."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class CursorPayload(Protocol):
    """Hook parsing operations required by orientation."""

    parse_payload: Callable[[str], dict[str, Any]]
    is_folded_cursor_session: Callable[[dict[str, Any]], bool]
    resolve_session_id: Callable[[str], str]
    resolve_root: Callable[[str], str]


def get_cursor_payload() -> CursorPayload:
    return cast(CursorPayload, load_port("orientation_cursor_payload", CursorPayload))
