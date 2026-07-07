"""Read-only probe that the connected DB carries the core's expected schema.

An HTTP-live core can still be schema-incomplete: the service answers
``/v1/health`` with 200 while a required table is missing and every route
that touches it fails at first query. The health payload's ``schema_ready``
field derives from this module so deploy gates assert schema readiness,
not just liveness.

``READINESS_TABLES`` is deliberately small — one representative table per
schema-initialization step in :func:`yoke_core.domain.schema_init.cmd_init`,
not the full expected-schema declaration the schema-drift doctor diffs —
so the probe stays a single cheap ``information_schema`` membership query
on a hot, unauthenticated endpoint. Names must stay clear of the
sensitive-token scan in
:mod:`yoke_core.tools.verify_env_auth_boundary` (no ``token``/``secret``/
``dsn``/``password`` substrings), since missing tables are echoed in the
public health payload.
"""

from __future__ import annotations

from typing import Any, List, Sequence, Tuple

READINESS_TABLES: Tuple[str, ...] = (
    "items",
    "projects",
    "events",
    "harness_sessions",
    "roles",
    "strategy_docs",
)


def missing_readiness_tables(
    conn: Any, tables: Sequence[str] = READINESS_TABLES
) -> List[str]:
    """Return the subset of *tables* absent from the connected database."""
    cur = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = current_schema() AND table_name = ANY(%s)",
        (list(tables),),
    )
    present = set()
    for row in cur.fetchall():
        present.add(row["table_name"] if isinstance(row, dict) else row[0])
    return [table for table in tables if table not in present]
