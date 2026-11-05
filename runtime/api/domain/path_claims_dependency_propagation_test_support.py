# ruff: noqa: E402, F401, F811
"""Shared setup for tests in this directory."""

from __future__ import annotations

from yoke_core.domain.path_claims_dependency_propagation import (
    propagate_release_unblock,
)

from runtime.api.domain._path_claims_test_helpers import (  # noqa: F401
    SNAP,
    conn,
    local_human,
    seed_target,
)


def _seed_item(conn, *, item_id: int, status: str = "implementing") -> int:
    conn.execute(
        "INSERT INTO items (id, title, workflow_id, workflow_version_id, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 'item', 'issue', (SELECT current_version_id FROM workflows WHERE id='issue'), %s, 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, %s)",
        (item_id, status, item_id),
    )
    conn.commit()
    return item_id


def _ensure_dep_table(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS item_dependencies ("
        "id INTEGER PRIMARY KEY, dependent_item_id INTEGER NOT NULL, "
        "blocking_item_id INTEGER NOT NULL, gate_point TEXT NOT NULL DEFAULT 'activation', "
        "satisfaction TEXT NOT NULL DEFAULT 'status:done', "
        "source TEXT NOT NULL, session_id TEXT, "
        "rationale TEXT NOT NULL DEFAULT '', "
        "evidence_json TEXT NOT NULL DEFAULT '{}', "
        "created_at TIMESTAMPTZ NOT NULL)"
    )
    conn.commit()


def _add_edge(
    conn,
    *,
    dependent: int,
    blocking: int,
    satisfaction: str = "status:done",
    gate_point: str = "activation",
):
    _ensure_dep_table(conn)
    conn.execute(
        "INSERT INTO item_dependencies (dependent_item_id, blocking_item_id, "
        "gate_point, satisfaction, source, created_at) "
        "VALUES (%s, %s, %s, %s, 'test', '2026-05-01T00:00:00Z')",
        (dependent, blocking, gate_point, satisfaction),
    )
    conn.commit()


def _seed_claim(
    conn,
    *,
    item_id: int,
    target_id: int,
    state: str,
    blocked_reason=None,
) -> int:
    actor = local_human(conn)
    row = conn.execute(
        "INSERT INTO path_claims "
        "(state, mode, owner_kind, owner_item_id, registered_by_actor_id, "
        "integration_target, registered_at, blocked_reason) "
        "VALUES (%s, 'exclusive', 'item', %s, %s, 'main', "
        "'2026-05-01T00:00:00Z', %s) RETURNING id",
        (state, item_id, actor, blocked_reason),
    ).fetchone()
    cid = int(row[0])
    if state == "active":
        conn.execute(
            "UPDATE path_claims SET activated_at = '2026-05-01T01:00:00Z', "
            "base_commit_sha = %s WHERE id = %s",
            (SNAP, cid),
        )
    conn.execute(
        "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
        "VALUES (%s, %s, '2026-05-01T00:00:00Z')",
        (cid, target_id),
    )
    conn.commit()
    return cid


def _release_directly(conn, claim_id: int):
    conn.execute(
        "UPDATE path_claims SET state = 'released', "
        "released_at = '2026-05-01T02:00:00Z', release_reason = 'test' "
        "WHERE id = %s",
        (claim_id,),
    )
    conn.commit()
