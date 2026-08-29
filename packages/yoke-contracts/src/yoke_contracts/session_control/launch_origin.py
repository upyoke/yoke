"""Who asked for a launch, recorded on the row rather than inferred later.

Every launch is created through the same state machine whatever asked for it,
so the ``origin`` column is the only place that difference survives — operator
listings and audit read it instead of guessing intent from the requester. The
operator is the only requester today; the column exists so the next one does
not have to be inferred.

One vocabulary, so the ``CREATE TABLE`` column and the additive ``ALTER``
that converges databases born before it cannot drift into two different
sets of allowed values.

``steering_backstop`` was removed from this vocabulary once the automatic
staffing pass that wrote it was gone. It had survived the feature by months as
a definition with no writer and one comparison that could never be true, which
left correctly-launched sessions falling through the arm after it and rendering
nothing. Databases created before the removal still carry it in their ``CHECK``
constraint, because only ``CREATE TABLE`` and the additive ``ADD COLUMN`` path
read the DDL below and neither narrows an existing constraint. That is harmless
text drift rather than a functional difference — every writer sets
``operator`` — and narrowing it everywhere would be a governed destructive
migration for no gain. ``HC-unreachable-vocabulary-value`` is the guard that
now catches this shape.
"""

from __future__ import annotations


LAUNCH_ORIGIN_OPERATOR = "operator"

LAUNCH_ORIGINS = (LAUNCH_ORIGIN_OPERATOR,)

LAUNCH_ORIGIN_VALUES_SQL = ", ".join(f"'{origin}'" for origin in LAUNCH_ORIGINS)

#: Identical text in the create and the additive alter.
ORIGIN_COLUMN_DDL = (
    f"TEXT NOT NULL DEFAULT '{LAUNCH_ORIGIN_OPERATOR}' "
    f"CHECK(origin IN ({LAUNCH_ORIGIN_VALUES_SQL}))"
)


__all__ = [
    "LAUNCH_ORIGINS",
    "LAUNCH_ORIGIN_OPERATOR",
    "LAUNCH_ORIGIN_VALUES_SQL",
    "ORIGIN_COLUMN_DDL",
]
