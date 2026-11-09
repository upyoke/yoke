"""JSON-safe values for diagnostic database output."""

from __future__ import annotations
import base64
import math
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID
from yoke_contracts.timestamps import format_instant


def json_safe(value: Any) -> Any:
    """Return *value* as a JSON-serializable value, unchanged in meaning."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return format_instant(value)
    if isinstance(value, (date, time, UUID)):
        return value.isoformat() if hasattr(value, "isoformat") else str(value)
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return base64.b64encode(value).decode("ascii")
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return str(value)
