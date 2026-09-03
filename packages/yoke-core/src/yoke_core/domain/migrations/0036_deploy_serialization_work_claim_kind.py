"""Admit the per-project deployment lock into the work-claim vocabulary.

Creating or executing a deployment run now requires the calling session
to hold a ``deploy_serialization`` claim on the project. The claim is an
ordinary ``work_claims`` row, but ``work_claims.target_kind`` carries a
CHECK constraint listing the kinds a database accepts, and a table that
already exists keeps the constraint it was created with. So a live
universe would refuse the very first deploy lock until this entry widens
its constraint.

Two properties this entry has to get right:

- **It is self-contained.** A history entry has to load from whatever
  build applies it, including a restored archive replaying its history,
  so the kind vocabulary is written here rather than imported from a
  module that shipped alongside it.
- **It only widens.** Adding a permitted value invalidates no stored row
  and breaks no reader, so a build running ahead of this entry and a
  build running behind it both serve the same data correctly. The
  exclusivity index is created here too, but the boot converge creates
  it idempotently as well, so a universe that never applies this entry
  still gets one from its own schema step.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _table_exists

MINIMUM_SERVING_VERSION = NEXT_RELEASE
CLAIM_TABLE = "work_claims"
TARGET_KIND_CONSTRAINT = "work_claims_target_kind_check"
TARGET_KIND_DEPLOY_SERIALIZATION = "deploy_serialization"
DEPLOY_SERIALIZATION_INDEX = "idx_work_claims_active_deploy_serialization"

#: The complete target-kind vocabulary after this entry.
ALL_TARGET_KINDS = (
    "item",
    "epic_task",
    "process",
    "steering",
    "migration_serialization",
    "qa_admission",
    "route_qualification",
    TARGET_KIND_DEPLOY_SERIALIZATION,
)


def _scope_text(conn: Any, key: str, column: str = "scope") -> str:
    """Read one scope value as text, in this connection's dialect."""
    if db_backend.connection_is_postgres(conn):
        return f"NULLIF({column}, '')::jsonb #>> '{{{key}}}'"
    return f"json_extract({column}, '$.{key}')"


def _widen_target_kind_check(conn: Any) -> None:
    if not db_backend.connection_is_postgres(conn):
        return
    kinds = ", ".join(f"'{kind}'" for kind in ALL_TARGET_KINDS)
    escaped = TARGET_KIND_CONSTRAINT.replace('"', '""')
    conn.execute(
        f'ALTER TABLE "{CLAIM_TABLE}" DROP CONSTRAINT IF EXISTS "{escaped}"'
    )
    conn.execute(
        f'ALTER TABLE "{CLAIM_TABLE}" ADD CONSTRAINT "{escaped}" '
        f"CHECK(target_kind IN ({kinds}))"
    )


def _create_deploy_serialization_index(conn: Any) -> None:
    project = _scope_text(conn, "project_id")
    conn.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {DEPLOY_SERIALIZATION_INDEX} "
        f"ON {CLAIM_TABLE}(({project})) WHERE released_at IS NULL "
        f"AND target_kind='{TARGET_KIND_DEPLOY_SERIALIZATION}'"
    )


def apply(conn: Any) -> None:
    if not _table_exists(conn, CLAIM_TABLE):
        return
    _widen_target_kind_check(conn)
    _create_deploy_serialization_index(conn)


def invariants(conn: Any) -> None:
    if not _table_exists(conn, CLAIM_TABLE):
        return
    from yoke_core.domain.schema_common import _get_indexes

    assert DEPLOY_SERIALIZATION_INDEX in set(_get_indexes(conn, CLAIM_TABLE)), (
        f"{CLAIM_TABLE} is missing index {DEPLOY_SERIALIZATION_INDEX}"
    )


__all__ = [
    "ALL_TARGET_KINDS",
    "CLAIM_TABLE",
    "DEPLOY_SERIALIZATION_INDEX",
    "MINIMUM_SERVING_VERSION",
    "TARGET_KIND_CONSTRAINT",
    "apply",
    "invariants",
]
