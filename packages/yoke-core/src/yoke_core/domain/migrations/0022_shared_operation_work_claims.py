"""Absorb the shared-operation lease table into typed work claims.

Migration territory, physical test machines, and private-route
qualification grants were coordinated by a second lock table keyed on
``(project_id, lease_key)``. They are now ordinary ``work_claims`` rows
with their own target kinds, so one system carries session binding,
heartbeat, sweep policy, and telemetry for every hold.

Three properties this entry has to get right:

- **It is self-contained.** A history entry has to load from whatever
  build applies it, including a restored archive replaying its history,
  so every name it needs is written here rather than imported from a
  module that shipped alongside it.
- **It folds instead of duplicating.** A universe can serve the new
  build before the entry applies, which means the running code has
  already written the claim row this entry would produce; re-inserting
  it would trip the new exclusivity indexes. Where the equivalent live
  claim exists, the lease row is dropped rather than migrated.
- **A hold with no surviving holder is released, not stranded.** A claim
  row is session-bound by foreign key. An active lease whose acquiring
  session is gone from ``harness_sessions`` cannot become one, and
  inventing a holder would hand the resource to a session that never
  took it. Those rows settle with the table: the resource frees, and the
  next caller acquires it cleanly.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _table_exists

MINIMUM_SERVING_VERSION = NEXT_RELEASE
LEASE_TABLE = "coordination_leases"
CLAIM_TABLE = "work_claims"
TARGET_KIND_CONSTRAINT = "work_claims_target_kind_check"

TARGET_KIND_MIGRATION_SERIALIZATION = "migration_serialization"
TARGET_KIND_QA_ADMISSION = "qa_admission"
TARGET_KIND_ROUTE_QUALIFICATION = "route_qualification"

#: The complete target-kind vocabulary after this entry, longest key
#: prefix first so a prefix extending another still resolves correctly.
ALL_TARGET_KINDS = (
    "item",
    "epic_task",
    "process",
    "steering",
    TARGET_KIND_MIGRATION_SERIALIZATION,
    TARGET_KIND_QA_ADMISSION,
    TARGET_KIND_ROUTE_QUALIFICATION,
)
COORDINATION_KEY_PREFIXES = (
    ("FLEET_PRIVATE_ROUTE_QUALIFICATION:v1:", TARGET_KIND_ROUTE_QUALIFICATION),
    ("LIVE_DB_MIGRATION:", TARGET_KIND_MIGRATION_SERIALIZATION),
    ("QA_HOST:", TARGET_KIND_QA_ADMISSION),
)

QA_ADMISSION_INDEX = "idx_work_claims_active_qa_admission"
ROUTE_QUALIFICATION_INDEX = "idx_work_claims_active_route_qualification"
MIGRATION_SERIALIZATION_INDEX = "idx_work_claims_active_migration_serialization"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _scope_text(conn: Any, key: str, column: str = "scope") -> str:
    """Read one scope value as text, in this connection's dialect."""
    if db_backend.connection_is_postgres(conn):
        return f"NULLIF({column}, '')::jsonb #>> '{{{key}}}'"
    return f"json_extract({column}, '$.{key}')"


def _encode_scope(scope: dict[str, Any]) -> str:
    """Serialize a scope exactly as the domain layer stores it."""
    return json.dumps(scope, sort_keys=True, separators=(",", ":"))


def _claim_scope_for_row(row: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Translate one lease row into its typed kind and scope, or None."""
    key = str(row.get("lease_key") or "")
    project_id = int(row.get("project_id") or 0)
    for prefix, kind in COORDINATION_KEY_PREFIXES:
        if not key.startswith(prefix):
            continue
        resource = key[len(prefix):]
        if not resource:
            return None
        if kind == TARGET_KIND_MIGRATION_SERIALIZATION:
            owner_item_id = row.get("owner_item_id")
            if owner_item_id is None or project_id <= 0:
                return None
            return kind, {
                "project_id": project_id,
                "model": resource,
                "item_id": int(owner_item_id),
            }
        if kind == TARGET_KIND_QA_ADMISSION:
            return kind, {"machine_id": resource}
        if project_id <= 0:
            return None
        return kind, {"project_id": project_id, "grant_key": resource}
    return None


def _known_sessions(conn: Any) -> set[str]:
    if not _table_exists(conn, "harness_sessions"):
        return set()
    return {
        str(row[0])
        for row in conn.execute(
            "SELECT session_id FROM harness_sessions"
        ).fetchall()
    }


def _already_claimed(conn: Any, kind: str, scope: dict[str, Any]) -> bool:
    """True when a live claim already holds this resource.

    Migration territory conflicts on (project_id, model) alone, because
    the owning item in its scope records who holds the territory rather
    than what is held.
    """
    p = _p(conn)
    if kind == TARGET_KIND_MIGRATION_SERIALIZATION:
        where = (
            f"target_kind = {p} "
            f"AND {_scope_text(conn, 'project_id')} = {p} "
            f"AND {_scope_text(conn, 'model')} = {p}"
        )
        params: list[Any] = [kind, str(scope["project_id"]), str(scope["model"])]
    else:
        where = f"target_kind = {p} AND scope = {p}"
        params = [kind, _encode_scope(scope)]
    row = conn.execute(
        f"SELECT 1 FROM {CLAIM_TABLE} WHERE {where} "
        "AND released_at IS NULL LIMIT 1",
        tuple(params),
    ).fetchone()
    return row is not None


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


def _create_coordination_indexes(conn: Any) -> None:
    conn.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {QA_ADMISSION_INDEX} "
        f"ON {CLAIM_TABLE}(scope) WHERE released_at IS NULL "
        f"AND target_kind='{TARGET_KIND_QA_ADMISSION}'"
    )
    conn.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {ROUTE_QUALIFICATION_INDEX} "
        f"ON {CLAIM_TABLE}(scope) WHERE released_at IS NULL "
        f"AND target_kind='{TARGET_KIND_ROUTE_QUALIFICATION}'"
    )
    project = _scope_text(conn, "project_id")
    model = _scope_text(conn, "model")
    conn.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {MIGRATION_SERIALIZATION_INDEX} "
        f"ON {CLAIM_TABLE}(({project}), ({model})) WHERE released_at IS NULL "
        f"AND target_kind='{TARGET_KIND_MIGRATION_SERIALIZATION}'"
    )


def _migrate_active_leases(conn: Any) -> None:
    sessions = _known_sessions(conn)
    p = _p(conn)
    rows = conn.execute(
        "SELECT id, project_id, lease_key, session_id, acquired_at, "
        "heartbeat_at, owner_item_id, owner_session_id "
        f"FROM {LEASE_TABLE} WHERE released_at IS NULL ORDER BY id"
    ).fetchall()
    for raw in rows:
        row = dict(raw)
        resolved = _claim_scope_for_row(row)
        if resolved is None:
            continue
        kind, scope = resolved
        holder = str(row.get("owner_session_id") or row.get("session_id") or "")
        if holder not in sessions:
            continue
        if _already_claimed(conn, kind, scope):
            continue
        acquired_at = str(row["acquired_at"])
        conn.execute(
            f"INSERT INTO {CLAIM_TABLE} "
            "(session_id, target_kind, scope, claim_type, claimed_at, "
            "last_heartbeat, released_at, release_reason) "
            f"VALUES ({p}, {p}, {p}, 'exclusive', {p}, {p}, NULL, NULL)",
            (
                holder,
                kind,
                _encode_scope(scope),
                acquired_at,
                str(row["heartbeat_at"] or acquired_at),
            ),
        )


def apply(conn: Any) -> None:
    if not _table_exists(conn, CLAIM_TABLE):
        return
    _widen_target_kind_check(conn)
    if _table_exists(conn, LEASE_TABLE):
        _migrate_active_leases(conn)
        conn.execute(f'DROP TABLE IF EXISTS "{LEASE_TABLE}"')
    _create_coordination_indexes(conn)


def invariants(conn: Any) -> None:
    if not _table_exists(conn, CLAIM_TABLE):
        return
    assert not _table_exists(conn, LEASE_TABLE), (
        f"{LEASE_TABLE} must be retired"
    )
    from yoke_core.domain.schema_common import _get_indexes

    indexes = set(_get_indexes(conn, CLAIM_TABLE))
    for name in (
        QA_ADMISSION_INDEX,
        ROUTE_QUALIFICATION_INDEX,
        MIGRATION_SERIALIZATION_INDEX,
    ):
        assert name in indexes, f"{CLAIM_TABLE} is missing index {name}"


__all__ = [
    "CLAIM_TABLE",
    "LEASE_TABLE",
    "MINIMUM_SERVING_VERSION",
    "TARGET_KIND_CONSTRAINT",
    "apply",
    "invariants",
]
