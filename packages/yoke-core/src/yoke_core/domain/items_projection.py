"""Operator-facing item projection vocabulary.

The default listing projection and the actor-label field set are domain
vocabulary: the server-side handlers and the CLI flag parsers both derive
their shapes from this module so the layers cannot drift.
"""

from __future__ import annotations

from yoke_contracts.time_sql import instant_wire_sql
from yoke_core.domain.stored_instant_columns import STORED_INSTANT_COLUMNS

ITEM_INSTANT_FIELDS = frozenset(
    column for table, column in STORED_INSTANT_COLUMNS if table == "items"
)


def item_text_expression(field: str, *, column: str | None = None) -> str:
    """Project a trusted item column for a textual query/pipe owner."""
    value = column or field
    expression = (
        instant_wire_sql(value)
        if field in ITEM_INSTANT_FIELDS
        else f"CAST({value} AS TEXT)"
    )
    return f"COALESCE({expression}, '')"


#: Columns whose emitted form is an actor display label rather than the
#: raw stored value (which is a numeric ``actors.id``).
ACTOR_LABEL_FIELDS = frozenset({"source", "owner"})

#: Default column projection for operator-facing item listings. ``id``
#: carries the public ``PREFIX-N`` ref; ``source`` carries the actor
#: display label. Item primary keys remain inside the engine.
DEFAULT_LIST_FIELDS: tuple[str, ...] = (
    "id",
    "title",
    "status",
    "priority",
    "workflow_id",
    "source",
)

DEFAULT_LIST_FIELDS_CSV = ",".join(DEFAULT_LIST_FIELDS)

__all__ = [
    "ACTOR_LABEL_FIELDS",
    "ITEM_INSTANT_FIELDS",
    "item_text_expression",
    "DEFAULT_LIST_FIELDS",
    "DEFAULT_LIST_FIELDS_CSV",
]
