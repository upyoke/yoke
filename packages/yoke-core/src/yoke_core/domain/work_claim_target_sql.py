"""SQL matching for typed work-claim targets.

Sibling of :mod:`yoke_core.domain.work_claim_targets`, which owns target
construction and validation. This module owns the other half: turning a
target into the SQL that finds its rows. Kept apart so the shape
authority stays readable and portable-SQL concerns live in one place.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_work_claim_sql import scope_text_sql
from yoke_core.domain.work_claim_targets import (
    STICKY_TARGET_KINDS,
    TARGET_KIND_MIGRATION_SERIALIZATION,
    TARGET_KIND_PROCESS,
    WorkClaimTarget,
)

#: The predicate every session-scoped release and reclaim adds so a
#: sticky claim is not swept out from under the resource it is holding.
#: Recovery for those kinds is the audited operator release instead.
LIVENESS_BOUND_SQL = "target_kind NOT IN (%s)" % ", ".join(
    f"'{kind}'" for kind in sorted(STICKY_TARGET_KINDS)
)


def liveness_bound_clause(alias: str = "") -> str:
    """Return :data:`LIVENESS_BOUND_SQL` qualified by a table alias."""
    return f"{alias}.{LIVENESS_BOUND_SQL}" if alias else LIVENESS_BOUND_SQL


#: Scope keys that form a kind's exclusivity unit when it is narrower than
#: the whole scope. A process claim conflicts on its conflict group and a
#: migration-serialization claim on the model it serializes — the rest of
#: each scope records who holds it or how it is addressed, not what is held.
_CONFLICT_KEYS = {
    TARGET_KIND_PROCESS: ("conflict_group",),
    TARGET_KIND_MIGRATION_SERIALIZATION: ("project_id", "model"),
}


def exact_match_clause(
    conn: Any,
    target: WorkClaimTarget,
    *,
    alias: str = "",
) -> tuple[str, list[Any]]:
    """Return SQL and params matching one exact canonical target."""
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    prefix = f"{alias}." if alias else ""
    return (
        f"{prefix}target_kind = {p} AND {prefix}scope = {p}",
        [target.kind, target.scope_json()],
    )


def conflict_match_clause(
    conn: Any,
    target: WorkClaimTarget,
    *,
    alias: str = "",
) -> tuple[str, list[Any]]:
    """Return SQL and params matching the target's exclusivity unit."""
    keys = _CONFLICT_KEYS.get(target.kind)
    if keys is None:
        return exact_match_clause(conn, target, alias=alias)
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    prefix = f"{alias}." if alias else ""
    clauses = [f"{prefix}target_kind = {p}"]
    params: list[Any] = [target.kind]
    for key in keys:
        clauses.append(f"{scope_text_sql(conn, f'{prefix}scope', key)} = {p}")
        params.append(str(target.scope[key]))
    return (" AND ".join(clauses), params)


__all__ = [
    "LIVENESS_BOUND_SQL",
    "conflict_match_clause",
    "exact_match_clause",
    "liveness_bound_clause",
]
