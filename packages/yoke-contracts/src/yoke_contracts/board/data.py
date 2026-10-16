"""JSON value fidelity for the named board snapshot contract."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from yoke_contracts.timestamps import format_instant, parse_instant

BOARD_DATA_VERSION = 3


class BoardDataError(RuntimeError):
    """Board data could not be produced or consumed."""


def _encode_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return {"__t": "decimal", "v": str(value)}
    if isinstance(value, datetime):
        return {"__t": "datetime", "v": format_instant(value)}
    if isinstance(value, date):
        return {"__t": "date", "v": value.isoformat()}
    if isinstance(value, dict):
        return {str(key): _encode_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode_value(item) for item in value]
    raise BoardDataError(
        f"board data cannot encode a {type(value).__name__} value; "
        "extend the codec in yoke_contracts.board.data"
    )


def _decode_value(value: Any) -> Any:
    if isinstance(value, dict) and "__t" in value:
        tag = value.get("__t")
        raw = value.get("v")
        if tag == "decimal":
            return Decimal(str(raw))
        if tag == "datetime":
            return parse_instant(raw)
        if tag == "date":
            return date.fromisoformat(str(raw))
        raise BoardDataError(f"board data carries unknown value tag {tag!r}")
    if isinstance(value, dict):
        return {key: _decode_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode_value(item) for item in value]
    return value
