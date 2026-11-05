# ruff: noqa: F811
"""Registration respects dependency direction and coordination-only overlap."""

from __future__ import annotations

from runtime.api.domain.path_claim_directional_overlap_test_support import (
    _add_dep_edge as _add_dep_edge,
    _ensure_item_dependencies_table as _ensure_item_dependencies_table,
    _seed_active_claim as _seed_active_claim,
    _seed_item as _seed_item,
)


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
