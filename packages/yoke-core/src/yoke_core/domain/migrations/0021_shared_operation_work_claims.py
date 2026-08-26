"""Absorb the shared-operation lease table into typed work claims.

Migration territory, physical test machines, and private-route
qualification grants were coordinated by a second lock table keyed on
``(project_id, lease_key)``. They are now ordinary ``work_claims`` rows
with their own target kinds, so one system carries session binding,
heartbeat, sweep policy, and telemetry for every hold.

Two properties this entry has to get right:

- **It folds instead of duplicating.** A universe can run the new build
  before this entry applies, which means the code has already written the
  claim row this entry would produce. Where the equivalent live claim
  exists, the lease row is dropped rather than re-inserted, so applying
  late cannot trip the new exclusivity indexes.
- **A hold with no surviving holder is released, not stranded.** A claim
  row is session-bound by foreign key. An active lease whose acquiring
  session is gone from ``harness_sessions`` cannot become one, and
  inventing a holder would hand the resource to a session that never took
  it. Those rows settle with the table: the resource frees, and the next
  caller acquires it cleanly.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.coordination_claim_keys import (
    COORDINATION_KEY_PREFIXES,
    TARGET_KIND_MIGRATION_SERIALIZATION,
    TARGET_KIND_QA_ADMISSION,
    TARGET_KIND_ROUTE_QUALIFICATION,
)
from yoke_core.domain import db_backend
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.schema_init_work_claim_indexes import (
    ACTIVE_MIGRATION_SERIALIZATION_INDEX_NAME,
    ACTIVE_QA_ADMISSION_INDEX_NAME,
    ACTIVE_ROUTE_QUALIFICATION_INDEX_NAME,
    create_work_claim_active_uniques,
)
from yoke_core.domain.work_claim_target_sql import (
    TARGET_KIND_CHECK_SQL,
    conflict_match_clause,
)
from yoke_core.domain.work_claim_targets import (
    WorkClaimTarget,
    encode_scope,
)

MINIMUM_SERVING_VERSION = NEXT_RELEASE
LEASE_TABLE = "coordination_leases"
CLAIM_TABLE = "work_claims"
TARGET_KIND_CONSTRAINT = "work_claims_target_kind_check"

def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _target_for(row: dict[str, Any]) -> WorkClaimTarget | None:
    """Translate one lease row into its typed target, or None if unknown."""
    key = str(row.get("lease_key") or "")
    project_id = int(row.get("project_id") or 0)
    for prefix, kind in COORDINATION_KEY_PREFIXES:
        if not key.startswith(prefix):
            continue
        suffix = key[len(prefix):]
        if not suffix:
            return None
        if kind == TARGET_KIND_MIGRATION_SERIALIZATION:
            owner_item_id = row.get("owner_item_id")
            if owner_item_id is None or project_id <= 0:
                return None
            return WorkClaimTarget(
                kind,
                {
                    "project_id": project_id,
                    "model": suffix,
                    "item_id": int(owner_item_id),
                },
            )
        if kind == TARGET_KIND_QA_ADMISSION:
            return WorkClaimTarget(kind, {"machine_id": suffix})
        if kind == TARGET_KIND_ROUTE_QUALIFICATION:
            if project_id <= 0:
                return None
            return WorkClaimTarget(
                kind, {"project_id": project_id, "grant_key": suffix}
            )
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


def _already_claimed(conn: Any, target: WorkClaimTarget) -> bool:
    where, params = conflict_match_clause(conn, target)
    row = conn.execute(
        f"SELECT 1 FROM {CLAIM_TABLE} WHERE {where} "
        "AND released_at IS NULL LIMIT 1",
        tuple(params),
    ).fetchone()
    return row is not None


def _widen_target_kind_check(conn: Any) -> None:
    if not db_backend.connection_is_postgres(conn):
        return
    escaped = TARGET_KIND_CONSTRAINT.replace('"', '""')
    conn.execute(
        f'ALTER TABLE "{CLAIM_TABLE}" DROP CONSTRAINT IF EXISTS "{escaped}"'
    )
    conn.execute(
        f'ALTER TABLE "{CLAIM_TABLE}" ADD CONSTRAINT "{escaped}" '
        f"CHECK({TARGET_KIND_CHECK_SQL})"
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
        target = _target_for(row)
        if target is None:
            continue
        holder = str(row.get("owner_session_id") or row.get("session_id") or "")
        if holder not in sessions:
            continue
        if _already_claimed(conn, target):
            continue
        acquired_at = str(row["acquired_at"])
        conn.execute(
            f"INSERT INTO {CLAIM_TABLE} "
            "(session_id, target_kind, scope, claim_type, claimed_at, "
            "last_heartbeat, released_at, release_reason) "
            f"VALUES ({p}, {p}, {p}, 'exclusive', {p}, {p}, NULL, NULL)",
            (
                holder,
                target.kind,
                encode_scope(target.scope),
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
    create_work_claim_active_uniques(conn)


def invariants(conn: Any) -> None:
    if not _table_exists(conn, CLAIM_TABLE):
        return
    assert not _table_exists(conn, LEASE_TABLE), (
        f"{LEASE_TABLE} must be retired"
    )
    from yoke_core.domain.schema_common import _get_indexes

    indexes = set(_get_indexes(conn, CLAIM_TABLE))
    for name in (
        ACTIVE_MIGRATION_SERIALIZATION_INDEX_NAME,
        ACTIVE_QA_ADMISSION_INDEX_NAME,
        ACTIVE_ROUTE_QUALIFICATION_INDEX_NAME,
    ):
        assert name in indexes, f"{CLAIM_TABLE} is missing index {name}"
    rows = conn.execute(
        f"SELECT target_kind, scope FROM {CLAIM_TABLE} ORDER BY id"
    ).fetchall()
    for row in rows:
        target_kind = row["target_kind"] if hasattr(row, "keys") else row[0]
        scope = row["scope"] if hasattr(row, "keys") else row[1]
        from yoke_core.domain.work_claim_targets import decode_scope

        WorkClaimTarget(str(target_kind), decode_scope(scope))


__all__ = [
    "CLAIM_TABLE",
    "LEASE_TABLE",
    "MINIMUM_SERVING_VERSION",
    "TARGET_KIND_CONSTRAINT",
    "apply",
    "invariants",
]
