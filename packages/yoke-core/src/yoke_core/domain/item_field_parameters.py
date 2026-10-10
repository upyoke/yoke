"""Bind item clocks through their declared semantic column ownership."""

from typing import Any

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.stored_instant_columns import STORED_INSTANT_COLUMNS

ITEM_INSTANT_FIELDS = frozenset(
    column for table, column in STORED_INSTANT_COLUMNS if table == "items"
)


def item_field_parameter(
    conn: Any, field: str, value: Any, *, text: bool = False
) -> Any:
    if field in ITEM_INSTANT_FIELDS:
        return instant_parameter(
            conn, parse_instant(value) if value is not None else None
        )
    return str(value) if text and value is not None else value
