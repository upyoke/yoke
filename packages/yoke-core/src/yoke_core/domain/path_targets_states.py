"""Single owner for ``path_targets.materialization_state`` literals.

The four known states are written here once so callers (planning,
materialization, resolve, register, read, render, readiness checks) and
the schema's CHECK domain stay in lockstep. The DDL itself remains
SQL-string and lists the literals inline; a Python-side test asserts
the DDL CHECK matches ``ALL_STATES`` so future additions land in both
surfaces atomically.

Adding a fifth state means: append to ``ALL_STATES`` here, update the
authoritative DDL in :mod:`yoke_core.domain.schema_init_path_tables`
and the fixture mirror in :mod:`runtime.api.fixtures.schema_ddl_runtime`,
ship a governed migration that rebuilds the table with the widened
CHECK, and the constant-owner test ratchets future surfaces onto the
new vocabulary.
"""

from __future__ import annotations


PLANNED = "planned"
OBSERVED = "observed"
ABANDONED = "abandoned"
TENTATIVE = "tentative"


ALL_STATES: tuple[str, ...] = (PLANNED, OBSERVED, ABANDONED, TENTATIVE)


PRE_OBSERVATION_STATES: tuple[str, ...] = (PLANNED, TENTATIVE)
"""States that represent a not-yet-observed reservation in the registry.

Materialization (snapshot scanner), readiness reference checks, and
abandon-on-cancel all treat these states the same way: they are valid
implementation surfaces that may flip to ``observed`` when git later
sees the path, and they are subject to abandonment when the owning
claim cancels and no other non-terminal claim still covers the path.
The two states differ only in operator-facing intent — ``planned``
declares an expected touch, ``tentative`` declares a possible-but-
uncertain touch — and in how they render.
"""


__all__ = [
    "ABANDONED",
    "ALL_STATES",
    "OBSERVED",
    "PLANNED",
    "PRE_OBSERVATION_STATES",
    "TENTATIVE",
]
