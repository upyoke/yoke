"""Runtime interface for cursor permissions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class CursorPermissions(Protocol):
    """Operations and values supplied by the executing adapter."""

    apply_cursor_permissions: Callable[..., Any]


def get_cursor_permissions() -> CursorPermissions:
    return cast(CursorPermissions, load_port("cursor_permissions", CursorPermissions))
