"""Normalize external commit clocks without fabricating missing evidence."""

from datetime import datetime
from typing import Any

from yoke_contracts.timestamps import InvalidInstant, parse_instant


def commit_instant(value: Any) -> datetime | None:
    """Missing or invalid external commit evidence cannot identify a landing."""
    if value is None or value == "":
        return None
    try:
        return parse_instant(value)
    except InvalidInstant:
        return None
