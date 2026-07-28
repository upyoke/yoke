# ruff: noqa: F811
"""Cross-surface directional path-claim overlap consistency tests."""

from yoke_core.domain.path_claims_overlap import (
    OverlapClassification,
    classify_overlap,
)
from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    conn,
    seed_target,
)
from runtime.api.domain.test_path_claim_directional_overlap import (
    _add_dep_edge,
    _seed_active_claim,
    _seed_item,
)


class TestCrossSurfaceConsistency:
    """AC-27: hard-block gate and classify_overlap agree on direction.

    The candidate (matching-shape) is the BLOCKER of a non-coord
    activation edge. Both surfaces must agree the candidate is upstream
    and does not wait: the hard-block gate query (which reads
    ``dependent_item = YOK-{candidate}`` directionally) returns no
    blockers for the candidate; ``classify_overlap`` returns ``NONE``.
    """

    def test_upstream_of_blocks_agrees_across_surfaces(self, conn):
        from yoke_core.domain.check_hard_blocks import _query_blockers

        target = seed_target(conn, path_string="runtime/api/domain")
        oth_item = _seed_item(conn, item_id=3011)
        cand_item = _seed_item(conn, item_id=3012)
        _seed_active_claim(conn, item_id=oth_item, target_id=target)
        _add_dep_edge(conn, dependent=oth_item, blocking=cand_item)

        overlap_verdict = classify_overlap(
            conn,
            target_ids=[target],
            integration_target="main",
            phase="register",
            candidate_item_id=cand_item,
        )
        assert overlap_verdict is OverlapClassification.NONE

        # Hard-block gate reads dependent_item directionally — the
        # candidate is the BLOCKER party here, so no row matches and
        # the gate returns an empty list (the candidate is not blocked).
        blockers = _query_blockers(
            conn,
            cand_item,
            gate_filter="activation",
        )
        assert blockers == []
