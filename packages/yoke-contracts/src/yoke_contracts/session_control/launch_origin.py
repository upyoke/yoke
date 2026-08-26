"""Who asked for a launch: an operator, or the automatic staffing backstop.

Both answers create the same launch through the same state machine, so the
row itself is the only place the difference survives.  Readers that need to
tell a hand-requested worker from one the steering backstop staffed — the
backstop's own concurrency budget, operator listings, audit — read the
``origin`` column rather than inferring intent from the requester.

One vocabulary, so the ``CREATE TABLE`` column and the additive ``ALTER``
that converges databases born before it cannot drift into two different
sets of allowed values.
"""

from __future__ import annotations


LAUNCH_ORIGIN_OPERATOR = "operator"
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
