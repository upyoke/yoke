"""Who asked for a launch, recorded on the row rather than inferred later.

Every launch is created through the same state machine whatever asked for it,
so the ``origin`` column is the only place that difference survives — operator
listings and audit read it instead of guessing intent from the requester.

``steering_backstop`` is a value the vocabulary still accepts and nothing
still writes: it marks launches filed by an automatic staffing pass the
steering seat no longer runs. Rows carrying it are live history, and the
``CHECK`` constraint has to keep admitting it or those rows stop validating,
so retiring the value is a governed destructive migration for no gain.

One vocabulary, so the ``CREATE TABLE`` column and the additive ``ALTER``
that converges databases born before it cannot drift into two different
sets of allowed values.
"""

from __future__ import annotations


LAUNCH_ORIGIN_OPERATOR = "operator"

#: Historical only — see the module docstring. No writer sets this.
LAUNCH_ORIGIN_STEERING_BACKSTOP = "steering_backstop"

LAUNCH_ORIGINS = (LAUNCH_ORIGIN_OPERATOR, LAUNCH_ORIGIN_STEERING_BACKSTOP)

LAUNCH_ORIGIN_VALUES_SQL = ", ".join(f"'{origin}'" for origin in LAUNCH_ORIGINS)

#: Identical text in the create and the additive alter.
ORIGIN_COLUMN_DDL = (
    f"TEXT NOT NULL DEFAULT '{LAUNCH_ORIGIN_OPERATOR}' "
    f"CHECK(origin IN ({LAUNCH_ORIGIN_VALUES_SQL}))"
)


__all__ = [
    "LAUNCH_ORIGINS",
    "LAUNCH_ORIGIN_OPERATOR",
    "LAUNCH_ORIGIN_STEERING_BACKSTOP",
    "LAUNCH_ORIGIN_VALUES_SQL",
    "ORIGIN_COLUMN_DDL",
]
