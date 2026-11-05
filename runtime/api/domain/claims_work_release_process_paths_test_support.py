# ruff: noqa: E402, F401, F811
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.domain._path_claims_test_helpers import (  # noqa: F401
    conn,
    seed_test_holder_session,
)

from yoke_contracts.timestamps import parse_instant

from yoke_core.domain.sessions_lifecycle_claim import release_claim

from yoke_core.domain.work_claim_targets import WorkClaimTarget, make_item_target


def _seed_process_work_claim(conn, *, session_id: str, process_key: str) -> int:
    seed_test_holder_session(conn, session_id=session_id)
    cur = conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, scope, "
        "claimed_at, last_heartbeat) "
        "VALUES (%s, 'process', %s, '2026-05-01T00:00:00Z', "
        "'2026-05-01T00:00:00Z') RETURNING id",
        (
            session_id,
            WorkClaimTarget(
                "process",
                {
                    "process_key": process_key,
                    "conflict_group": "strategy-control-plane:yoke",
                },
            ).scope_json(),
        ),
    )
    return int(cur.fetchone()[0])


def _seed_linked_path_claim(conn, *, work_claim_id: int, state: str = "active") -> int:
    cur = conn.execute(
        "INSERT INTO path_claims "
        "(state, mode, owner_kind, owner_work_claim_id, "
        "registered_by_actor_id, integration_target, registered_at) "
        "VALUES (%s, 'exclusive', 'process', %s, 1, 'main', "
        "'2026-05-01T00:00:00Z') RETURNING id",
        (state, work_claim_id),
    )
    return int(cur.fetchone()[0])
