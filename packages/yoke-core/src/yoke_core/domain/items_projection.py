"""Operator-facing item projection vocabulary.

The default listing projection and the actor-label field set are domain
vocabulary: the server-side handlers and the CLI flag parsers both derive
their shapes from this module so the layers cannot drift.
"""

from __future__ import annotations

#: Columns whose emitted form is an actor display label rather than the
#: raw stored value (which is a numeric ``actors.id``).
ACTOR_LABEL_FIELDS = frozenset({"source", "owner"})

#: Default column projection for operator-facing item listings. ``id``
#: carries the public ``PREFIX-N`` ref; ``source`` carries the actor
#: display label; the numeric primary key is the explicit ``internal_id``
#: opt-in and is deliberately absent from the default.
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
    "DEFAULT_LIST_FIELDS",
    "DEFAULT_LIST_FIELDS_CSV",
]
