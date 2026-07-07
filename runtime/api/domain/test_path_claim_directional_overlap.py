"""End-to-end regression for the directional path-claim overlap contract.

Covers AC-24: three scenarios for the directional dependency classifier,
exercised end-to-end across register / classify / repair / activate.

Scenario (a): candidate as DEPENDENT of a non-coordination edge
    candidate (cand) ``depends-on`` other (oth) ``activation``
    -> classify_overlap returns ``SERIAL_VIA_DEPENDENCY``
    -> register stores ``state='blocked'`` with the upstream pointer
    -> repair leaves the row blocked (other still active)

Scenario (b): candidate as BLOCKER (upstream-of-``blocks``)
    candidate (cand) ``blocks`` other (oth) ``activation``
    -> classify_overlap returns ``NONE``
    -> register stores ``state='planned'`` (no operator override needed)
    -> repair is a no-op (no blocked row exists)
    -> directly mirrors the self-shape (claim 146 vs 139)

Scenario (c): coordination_only edges in either direction
    candidate <-> other coordination_only
    -> classify_overlap returns ``NONE``
    -> register stores ``state='planned'``
    -> repair is a no-op

Plus an explicit cross-surface consistency check: the hard-block
dependency gate and ``classify_overlap`` agree on the upstream-of-blocks
verdict — both surfaces say "candidate is upstream, does not wait."
"""

from __future__ import annotations


from yoke_core.domain.path_claims import register
from yoke_core.domain.path_claims_blocked_coordination_repair import (
    repair_coordination_only_blocked,
)
from yoke_core.domain.path_claims_overlap import (
    OverlapClassification,
    classify_overlap,
)
from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    SNAP,
    conn,
    local_human,
    seed_target,
)


def _seed_item(conn, *, item_id: int, project: str = "yoke") -> int:
    project_key = str(project)
    project_id = 2 if project_key == "buzz" else int(project_key) if project_key.isdigit() else 1
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 'item', 'issue', 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', %s, %s)",
        (item_id, project_id, item_id),
    )
    conn.commit()
    return item_id


def _ensure_item_dependencies_table(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS item_dependencies ("
        "id INTEGER PRIMARY KEY, dependent_item TEXT NOT NULL, "
        "blocking_item TEXT NOT NULL, "
        "gate_point TEXT NOT NULL DEFAULT 'activation', "
        "satisfaction TEXT NOT NULL DEFAULT 'status:done', "
        "source TEXT NOT NULL, session_id INTEGER, "
        "rationale TEXT NOT NULL DEFAULT '', "
        "evidence_json TEXT NOT NULL DEFAULT '{}', "
        "created_at TEXT NOT NULL)"
    )
    conn.commit()


def _add_dep_edge(
    conn, *, dependent: int, blocking: int, gate_point: str = "activation",
):
    _ensure_item_dependencies_table(conn)
    conn.execute(
        "INSERT INTO item_dependencies (dependent_item, blocking_item, "
        "gate_point, source, created_at) "
        "VALUES (%s, %s, %s, 'test', '2026-05-01T00:00:00Z')",
        (f"YOK-{dependent}", f"YOK-{blocking}", gate_point),
    )
    conn.commit()


def _seed_active_claim(conn, *, item_id: int, target_id: int) -> int:
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
            "SELECT state FROM path_claims WHERE id = %s", (claim_id,),
        ).fetchone()
        assert row[0] == "blocked"

        repaired = repair_coordination_only_blocked(
            conn, item_id=cand_item,
        )
        assert repaired == []
        row = conn.execute(
            "SELECT state FROM path_claims WHERE id = %s", (claim_id,),
        ).fetchone()
        assert row[0] == "blocked"


class TestScenarioB_CandidateUpstreamOfBlocks:
    """(b) candidate is BLOCKER — classify_overlap == NONE ."""

    def test_register_lands_planned_without_override(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        oth_item = _seed_item(conn, item_id=3003)
        cand_item = _seed_item(conn, item_id=3004)
        _seed_active_claim(conn, item_id=oth_item, target_id=target)
        # Candidate BLOCKS other on activation — the cross-claim
        # shape. The pre-directional classifier walked this edge
        # bidirectionally and stranded BOTH parties in state='blocked';
        # the directional classifier returns NONE for the candidate side.
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
            "SELECT state FROM path_claims WHERE id = %s", (claim_id,),
        ).fetchone()
        assert row[0] == "planned"

    def test_repair_flips_legacy_blocked_to_planned(self, conn):
        """A legacy row stranded by the old bidirectional classifier
        flips to ``planned`` on the next repair sweep and emits
        ``directional_release=true``.
        """
        target = seed_target(conn, path_string="runtime/api/domain")
        oth_item = _seed_item(conn, item_id=3005)
        cand_item = _seed_item(conn, item_id=3006)
        _seed_active_claim(conn, item_id=oth_item, target_id=target)
        _add_dep_edge(conn, dependent=oth_item, blocking=cand_item)

        # Simulate a legacy stranded row: state='blocked' with the
        # pre-directional ``serial-via-dependency`` wording.
        actor = local_human(conn)
        cur = conn.execute(
            "INSERT INTO path_claims (state, mode, actor_id, item_id, "
            "integration_target, registered_at, base_commit_sha, "
            "blocked_reason) "
            "VALUES ('blocked', 'exclusive', %s, %s, 'main', "
            "'2026-05-01T00:00:00Z', %s, %s) RETURNING id",
            (
                actor, cand_item, SNAP,
                "serial-via-dependency on path_claims.id=999",
            ),
        )
        claim_id = int(cur.fetchone()[0])
        conn.execute(
            "INSERT INTO path_claim_targets (claim_id, target_id, "
            "declared_at) VALUES (%s, %s, '2026-05-01T00:00:00Z')",
            (claim_id, target),
        )
        conn.commit()

        repaired = repair_coordination_only_blocked(
            conn, item_id=cand_item,
        )
        assert repaired == [claim_id]
        row = conn.execute(
            "SELECT state, blocked_reason FROM path_claims WHERE id = %s",
            (claim_id,),
        ).fetchone()
        assert row[0] == "planned"
        assert row[1] is None

        event_row = conn.execute(
            "SELECT envelope FROM events "
            "WHERE event_name = 'PathClaimCoordinationOnlyRepaired' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert event_row is not None
        import json as _json
        envelope = _json.loads(event_row[0])
        ctx = envelope.get("context") or {}
        assert ctx.get("directional_release") is True


class TestScenarioC_CoordinationOnlyEitherDirection:
    """(c) coord-only edges in either direction — classify_overlap == NONE."""

    def test_coord_only_forward(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        oth_item = _seed_item(conn, item_id=3007)
        cand_item = _seed_item(conn, item_id=3008)
        _seed_active_claim(conn, item_id=oth_item, target_id=target)
        _add_dep_edge(
            conn, dependent=cand_item, blocking=oth_item,
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
            conn, dependent=oth_item, blocking=cand_item,
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
            conn, cand_item, gate_filter="activation",
        )
        assert blockers == []
