"""AC-20 widen-direction dep-graph awareness tests.

When a claim that registered with a non-terminal item_dependencies edge
widens its coverage, the widen-phase classify_overlap call inherits the
same dep-graph awareness so the operator does not have to cancel-and-
re-register just to add new files. Bidirectional: an edge in either
direction permits widen.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.path_claims_amend import widen
from yoke_core.domain.path_claims import IncompatibleOverlap
from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    SNAP,
    conn,
    local_human,
    seed_target,
)


def _seed_item(conn, *, item_id: int) -> int:
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 'item', 'issue', 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, %s)",
        (item_id, item_id),
    )
    conn.commit()
    return item_id


def _ensure_dep_table(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS item_dependencies ("
        "id INTEGER PRIMARY KEY, dependent_item TEXT NOT NULL, "
        "blocking_item TEXT NOT NULL, gate_point TEXT NOT NULL DEFAULT 'activation', "
        "satisfaction TEXT NOT NULL DEFAULT 'status:done', "
        "source TEXT NOT NULL, session_id INTEGER, "
        "rationale TEXT NOT NULL DEFAULT '', "
        "evidence_json TEXT NOT NULL DEFAULT '{}', "
        "created_at TEXT NOT NULL)"
    )
    conn.commit()


def _add_edge(conn, *, dependent: int, blocking: int):
    _ensure_dep_table(conn)
    conn.execute(
        "INSERT INTO item_dependencies (dependent_item, blocking_item, "
        "source, created_at) VALUES (%s, %s, 'test', '2026-05-01T00:00:00Z')",
        (f"YOK-{dependent}", f"YOK-{blocking}"),
    )
    conn.commit()


def _seed_active_claim_with_targets(
    conn, *, item_id: int, target_ids: list,
) -> int:
    actor = local_human(conn)
    cur = conn.execute(
        "INSERT INTO path_claims "
        "(state, mode, actor_id, item_id, integration_target, registered_at, "
        "activated_at, base_commit_sha) "
        "VALUES ('active', 'exclusive', %s, %s, 'main', "
        "'2026-05-01T00:00:00Z', '2026-05-01T01:00:00Z', %s) RETURNING id",
        (actor, item_id, SNAP),
    )
    cid = int(cur.fetchone()[0])
    for tid in target_ids:
        conn.execute(
            "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
            "VALUES (%s, %s, '2026-05-01T00:00:00Z')",
            (cid, tid),
        )
    conn.commit()
    return cid


def _seed_planned_claim_with_targets(
    conn, *, item_id: int, target_ids: list,
) -> int:
    actor = local_human(conn)
    cur = conn.execute(
        "INSERT INTO path_claims "
        "(state, mode, actor_id, item_id, integration_target, registered_at) "
        "VALUES ('planned', 'exclusive', %s, %s, 'main', "
        "'2026-05-01T00:00:00Z') RETURNING id",
        (actor, item_id),
    )
    cid = int(cur.fetchone()[0])
    for tid in target_ids:
        conn.execute(
            "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
            "VALUES (%s, %s, '2026-05-01T00:00:00Z')",
            (cid, tid),
        )
    conn.commit()
    return cid


class TestWidenForwardEdge:
    def test_widen_succeeds_when_candidate_has_edge(self, conn):
        # YOK-A holds an active claim covering t1.
        # YOK-B (depends on YOK-A) holds a planned claim covering t2.
        # B widens to also cover t1 — t1 overlaps A, but the dep edge
        # makes it serial.
        t1 = seed_target(conn, path_string="runtime/api/domain")
        t2 = seed_target(conn, path_string="docs")
        a_item = _seed_item(conn, item_id=5101)
        b_item = _seed_item(conn, item_id=5102)
        _seed_active_claim_with_targets(
            conn, item_id=a_item, target_ids=[t1],
        )
        b_claim = _seed_planned_claim_with_targets(
            conn, item_id=b_item, target_ids=[t2],
        )
        _add_edge(conn, dependent=b_item, blocking=a_item)

        # widen B to also cover t1 — should succeed.
        widen(
            conn,
            claim_id=b_claim,
            add_target_ids=[t1],
            reason="add t1 to B",
        )
        # B's coverage should now include t1.
        target_count = conn.execute(
            "SELECT COUNT(*) FROM path_claim_targets WHERE claim_id = %s",
            (b_claim,),
        ).fetchone()[0]
        assert target_count == 2


class TestWidenReverseEdge:
    def test_widen_succeeds_when_blocker_has_edge(self, conn):
        # Scenario: YOK-A holds an active claim, YOK-B
        # registered with --upstream-claim-id A. A wants to widen its
        # coverage to a path that B has — without bidirectional dep
        # awareness this would fail. With AC-20 it succeeds because B
        # depends on A.
        t1 = seed_target(conn, path_string="runtime/api/domain")
        t2 = seed_target(conn, path_string="docs")
        a_item = _seed_item(conn, item_id=5201)
        b_item = _seed_item(conn, item_id=5202)
        a_claim = _seed_active_claim_with_targets(
            conn, item_id=a_item, target_ids=[t1],
        )
        _seed_planned_claim_with_targets(
            conn, item_id=b_item, target_ids=[t2],
        )
        _add_edge(conn, dependent=b_item, blocking=a_item)

        # A widens to also cover t2 (B's territory). Without AC-20 this
        # would reject; with bidirectional awareness it succeeds.
        widen(
            conn,
            claim_id=a_claim,
            add_target_ids=[t2],
            reason="A absorbs t2",
        )
        target_count = conn.execute(
            "SELECT COUNT(*) FROM path_claim_targets WHERE claim_id = %s",
            (a_claim,),
        ).fetchone()[0]
        assert target_count == 2


class TestWidenRejectsWhenNoEdge:
    def test_widen_rejects_without_dep_edge(self, conn):
        t1 = seed_target(conn, path_string="runtime/api/domain")
        t2 = seed_target(conn, path_string="docs")
        a_item = _seed_item(conn, item_id=5301)
        b_item = _seed_item(conn, item_id=5302)
        _seed_active_claim_with_targets(
            conn, item_id=a_item, target_ids=[t1],
        )
        b_claim = _seed_planned_claim_with_targets(
            conn, item_id=b_item, target_ids=[t2],
        )
        _ensure_dep_table(conn)
        # No dep edge — widening B onto t1 should reject.
        with pytest.raises(IncompatibleOverlap):
            widen(
                conn,
                claim_id=b_claim,
                add_target_ids=[t1],
                reason="overlap without serial",
            )
