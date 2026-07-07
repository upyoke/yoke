"""Operation inventory rows for ephemeral environment wrappers."""

from __future__ import annotations

from typing import Tuple

from yoke_cli.operation_inventory_model import _Row, _w


WRAPPED_ROWS: Tuple[_Row, ...] = (
    _w("yoke ephemeral-env update", "ephemeral_env"),
)


__all__ = ["WRAPPED_ROWS"]
