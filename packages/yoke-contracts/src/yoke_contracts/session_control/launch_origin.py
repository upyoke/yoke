"""Who asked for a launch, recorded on the row rather than inferred later.

Every launch is created through the same state machine whatever asked for it,
so the ``origin`` column is the only place that difference survives — operator
listings, fleet balance, and audit read it instead of guessing intent from
the requester. The value is derived at insert from live authority: a creating
session that holds a steering claim for the launch's project records
``steering``; anything else records ``operator``. Callers cannot set the
value. Historical rows are left as they were written.

One vocabulary, so the ``CREATE TABLE`` column and the additive ``ALTER``
that converges databases born before it cannot drift into two different
sets of allowed values. Existing databases keep whatever ``CHECK`` they were
born with until a governed history entry replaces it; additive converge
never rewrites a constraint that is already there.

``steering_backstop`` was removed from this vocabulary once the automatic
staffing pass that wrote it was gone. Leftover rows with that value fail a
later CHECK rewrite loudly rather than being rewritten. Databases created
before the removal may still name it in an old ``CHECK`` until that rewrite
lands. ``HC-unreachable-vocabulary-value`` is the guard that catches a
definition with no producer.
"""

from __future__ import annotations


LAUNCH_ORIGIN_OPERATOR = "operator"
LAUNCH_ORIGIN_STEERING = "steering"

LAUNCH_ORIGINS = (LAUNCH_ORIGIN_OPERATOR, LAUNCH_ORIGIN_STEERING)

LAUNCH_ORIGIN_VALUES_SQL = ", ".join(f"'{origin}'" for origin in LAUNCH_ORIGINS)

#: Identical text in the create and the additive alter.
ORIGIN_COLUMN_DDL = (
    f"TEXT NOT NULL DEFAULT '{LAUNCH_ORIGIN_OPERATOR}' "
    f"CHECK(origin IN ({LAUNCH_ORIGIN_VALUES_SQL}))"
)


__all__ = [
    "LAUNCH_ORIGINS",
    "LAUNCH_ORIGIN_OPERATOR",
    "LAUNCH_ORIGIN_STEERING",
    "LAUNCH_ORIGIN_VALUES_SQL",
    "ORIGIN_COLUMN_DDL",
]
