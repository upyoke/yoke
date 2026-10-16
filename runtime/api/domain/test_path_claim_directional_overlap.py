# ruff: noqa: F811
"""Registration respects dependency direction and coordination-only overlap."""

from __future__ import annotations


from yoke_core.domain.path_claims import register
from yoke_core.domain.path_claims_overlap import (
    OverlapClassification,
    classify_overlap,
)
from runtime.api.domain._path_claims_test_helpers import (  # noqa: F401
    SNAP,
    conn,
    local_human,
    seed_target,
)


def _seed_item(conn, *, item_id: int, project: str = "yoke") -> int:
    project_key = str(project)
    project_id = (
        2
        if project_key == "externalwebapp"
        else int(project_key)
        if project_key.isdigit()
        else 1
    )
    conn.execute(
        "INSERT INTO items (id, title, workflow_id, workflow_version_id, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 'item', 'issue', (SELECT current_version_id FROM workflows WHERE id='issue'), 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', %s, %s)",
        (item_id, project_id, item_id),
    )
    conn.commit()
    return item_id


def _ensure_item_dependencies_table(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS item_dependencies ("
        "id INTEGER PRIMARY KEY, dependent_item_id INTEGER NOT NULL, "
        "blocking_item_id INTEGER NOT NULL, "
        "gate_point TEXT NOT NULL DEFAULT 'activation', "
        "satisfaction TEXT NOT NULL DEFAULT 'status:done', "
        "source TEXT NOT NULL, session_id INTEGER, "
        "rationale TEXT NOT NULL DEFAULT '', "
        "evidence_json TEXT NOT NULL DEFAULT '{}', "
        "created_at TIMESTAMPTZ NOT NULL)"
    )
    conn.commit()


def _add_dep_edge(
    conn,
    *,
    dependent: int,
    blocking: int,
    gate_point: str = "activation",
):
    _ensure_item_dependencies_table(conn)
    conn.execute(
        "INSERT INTO item_dependencies (dependent_item_id, blocking_item_id, "
        "gate_point, source, created_at) "
        "VALUES (%s, %s, %s, 'test', '2026-05-01T00:00:00Z')",
        (dependent, blocking, gate_point),
    )
    conn.commit()


def _seed_active_claim(conn, *, item_id: int, target_id: int) -> int:
    actor = local_human(conn)
    cur = conn.execute(
        "INSERT INTO path_claims "
        "(state, mode, owner_kind, owner_item_id, registered_by_actor_id, "
        "integration_target, registered_at, activated_at, base_commit_sha) "
        "VALUES ('active', 'exclusive', 'item', %s, %s, 'main', "
        "'2026-05-01T00:00:00Z', '2026-05-01T01:00:00Z', %s) RETURNING id",
        (item_id, actor, SNAP),
    )
    cid = int(cur.fetchone()[0])
    conn.execute(
        "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
        "VALUES (%s, %s, '2026-05-01T00:00:00Z')",
        (cid, target_id),
    )
    conn.commit()
    return cid


class TestScenarioA_CandidateDependent:
    """(a) candidate is DEPENDENT — classify_overlap == SERIAL_VIA_DEPENDENCY."""

    def test_register_blocks_with_dep_serial(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        oth_item = _seed_item(conn, item_id=3001)
        cand_item = _seed_item(conn, item_id=3002)
        _seed_active_claim(conn, item_id=oth_item, target_id=target)
        _add_dep_edge(conn, dependent=cand_item, blocking=oth_item)

        verdict = classify_overlap(
            conn,
            target_ids=[target],
            integration_target="main",
            phase="register",
            candidate_item_id=cand_item,
        )
        assert verdict is OverlapClassification.SERIAL_VIA_DEPENDENCY

        claim_id = register(
            conn,
            actor_id=local_human(conn),
            integration_target="main",
            target_ids=[target],
            item_id=cand_item,
        )
        row = conn.execute(
            "SELECT state FROM path_claims WHERE id = %s",
            (claim_id,),
        ).fetchone()
        assert row[0] == "blocked"


class TestScenarioB_CandidateUpstreamOfBlocks:
    """(b) candidate is BLOCKER — classify_overlap == NONE ."""

    def test_register_lands_planned_without_override(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        oth_item = _seed_item(conn, item_id=3003)
        cand_item = _seed_item(conn, item_id=3004)
        _seed_active_claim(conn, item_id=oth_item, target_id=target)
        # The upstream candidate does not wait for its dependent.
        _add_dep_edge(conn, dependent=oth_item, blocking=cand_item)

        verdict = classify_overlap(
            conn,
            target_ids=[target],
            integration_target="main",
            phase="register",
            candidate_item_id=cand_item,
        )
        assert verdict is OverlapClassification.NONE

        claim_id = register(
            conn,
            actor_id=local_human(conn),
            integration_target="main",
            target_ids=[target],
            item_id=cand_item,
        )
        row = conn.execute(
            "SELECT state FROM path_claims WHERE id = %s",
            (claim_id,),
        ).fetchone()
        assert row[0] == "planned"


class TestScenarioC_CoordinationOnlyEitherDirection:
    """(c) coord-only edges in either direction — classify_overlap == NONE."""

    def test_coord_only_forward(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        oth_item = _seed_item(conn, item_id=3007)
        cand_item = _seed_item(conn, item_id=3008)
        _seed_active_claim(conn, item_id=oth_item, target_id=target)
        _add_dep_edge(
            conn,
            dependent=cand_item,
            blocking=oth_item,
            gate_point="coordination_only",
        )

        verdict = classify_overlap(
            conn,
            target_ids=[target],
            integration_target="main",
            phase="register",
            candidate_item_id=cand_item,
        )
        assert verdict is OverlapClassification.NONE

    def test_coord_only_reverse(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        oth_item = _seed_item(conn, item_id=3009)
        cand_item = _seed_item(conn, item_id=3010)
        _seed_active_claim(conn, item_id=oth_item, target_id=target)
        _add_dep_edge(
            conn,
            dependent=oth_item,
            blocking=cand_item,
            gate_point="coordination_only",
        )

        verdict = classify_overlap(
            conn,
            target_ids=[target],
            integration_target="main",
            phase="register",
            candidate_item_id=cand_item,
        )
        assert verdict is OverlapClassification.NONE
