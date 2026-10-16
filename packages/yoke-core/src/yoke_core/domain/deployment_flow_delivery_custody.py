"""Explicit delivery custody on a flow; new flows take custody by default."""

from __future__ import annotations

from typing import Any


COLUMN = "takes_delivery_custody"


def parse_takes_delivery_custody(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1"):
            return True
        if normalized in ("false", "0"):
            return False
    raise ValueError("takes_delivery_custody must be a boolean")


def resolve_takes_delivery_custody(value: Any) -> bool:
    if value is None:
        return True
    return parse_takes_delivery_custody(value)


def as_sql_int(value: bool) -> int:
    return 1 if value else 0


def from_cell(value: Any) -> bool:
    if value is None:
        return False
    return parse_takes_delivery_custody(value)


__all__ = [
    "COLUMN",
    "as_sql_int",
    "from_cell",
    "parse_takes_delivery_custody",
    "resolve_takes_delivery_custody",
]
