"""Overlap classifier tests for the path-claim domain.

Split from ``test_path_claims.py`` once the parent crossed the
file-line gate. The classifier under test lives in
``path_claims_overlap`` and exposes the dual-mode `phase` parameter
(`'register'` checks the full non-terminal frontier; `'activate'`
only checks `active` siblings).
"""

from __future__ import annotations

from yoke_core.domain._path_claims_test_helpers import (
    SNAP,
    conn,  # noqa: F401  (pytest fixture)
    local_human,
    seed_target,
)
from yoke_core.domain.path_claims import activate, register
from yoke_core.domain.path_claims_overlap import (
    OverlapClassification,
    classify_overlap,
)


class TestOverlapClassifier:
    def test_disjoint_returns_none(self, conn):
        actor = local_human(conn)
        a = seed_target(conn, path_string="runtime/api/domain")
        b = seed_target(conn, path_string="runtime/harness")
        register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[a],
        )
        result = classify_overlap(
            conn,
            target_ids=[b],
            integration_target="main",
        )
        assert result is OverlapClassification.NONE

    def test_overlap_with_active_is_incompatible(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        first = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
        )
        activate(conn, claim_id=first, base_commit_sha=SNAP)
        result = classify_overlap(
            conn,
            target_ids=[target],
            integration_target="main",
        )
        assert result is OverlapClassification.INCOMPATIBLE

    def test_overlap_with_named_upstream_is_serial(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        upstream = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
        )
        result = classify_overlap(
            conn,
            target_ids=[target],
            integration_target="main",
            upstream_claim_id=upstream,
        )
        assert result is OverlapClassification.SERIAL_VIA_DEPENDENCY

    def test_named_upstream_does_not_hide_second_overlap(self, conn):
        actor = local_human(conn)
        a = seed_target(conn, path_string="runtime/api/domain")
        b = seed_target(conn, path_string="runtime/harness")
        upstream = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[a],
        )
        register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[b],
        )
        result = classify_overlap(
            conn,
            target_ids=[a, b],
            integration_target="main",
            upstream_claim_id=upstream,
        )
        assert result is OverlapClassification.INCOMPATIBLE

    def test_excludes_self(self, conn):
        """Re-classifying for `activate()` must not count the candidate's
        own row against itself."""
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        claim_id = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
        )
        result = classify_overlap(
            conn,
            target_ids=[target],
            integration_target="main",
            exclude_claim_id=claim_id,
        )
        assert result is OverlapClassification.NONE

    def test_phase_activate_skips_planned_siblings(self, conn):
        """At activation phase, planned/blocked siblings do not block.

        Only ``active`` siblings hold the door lock; the candidate's
        activation should not be rejected just because another claim
        registered (but never activated) on the same target.
        """
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
        )
        # Phase=register would say INCOMPATIBLE; phase=activate says NONE.
        register_phase = classify_overlap(
            conn,
            target_ids=[target],
            integration_target="main",
            phase="register",
        )
        activate_phase = classify_overlap(
            conn,
            target_ids=[target],
            integration_target="main",
            phase="activate",
        )
        assert register_phase is OverlapClassification.INCOMPATIBLE
        assert activate_phase is OverlapClassification.NONE


def _seed_item_for_overlap(conn, *, item_id: int) -> int:
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 'item', 'issue', 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, %s)",
        (item_id, item_id),
    )
    conn.commit()
    return item_id


def _ensure_item_dependencies(conn):
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


def _add_dep_edge(conn, *, dependent: int, blocking: int, gate_point: str):
    _ensure_item_dependencies(conn)
    conn.execute(
        "INSERT INTO item_dependencies (dependent_item, blocking_item, "
        "gate_point, source, created_at) "
        "VALUES (%s, %s, %s, 'test', '2026-05-01T00:00:00Z')",
        (f"YOK-{dependent}", f"YOK-{blocking}", gate_point),
    )
    conn.commit()


class TestCoordinationOnlySemantics:
    """Coordination-only dep edges no longer serialize at path-claim time.

    The four classification cases the new contract pins:

    * AC-1: coord-only-only between candidate and blocker -> ``NONE``.
    * AC-2: mixed coord-only + ``activation`` -> ``SERIAL_VIA_DEPENDENCY``.
    * AC-3: explicit ``--upstream-claim-id`` forces serial regardless.
    * AC-4: no ``item_dependencies`` edge between the pair -> ``INCOMPATIBLE``
      (existing behaviour preserved; covered by
      ``test_overlap_with_active_is_incompatible`` above).
    """

    def _stage(self, conn, *, blk_item_id: int, cand_item_id: int):
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        _seed_item_for_overlap(conn, item_id=blk_item_id)
        _seed_item_for_overlap(conn, item_id=cand_item_id)
        blk_claim = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
            item_id=blk_item_id,
        )
        return target, blk_claim

    def test_coordination_only_edge_yields_none(self, conn):
        target, _ = self._stage(conn, blk_item_id=2201, cand_item_id=2202)
        _add_dep_edge(
            conn, dependent=2202, blocking=2201,
            gate_point="coordination_only",
        )
        outcome = classify_overlap(
            conn,
            target_ids=[target],
            integration_target="main",
            phase="register",
            candidate_item_id=2202,
        )
        assert outcome is OverlapClassification.NONE

    def test_coordination_only_edge_reverse_direction_yields_none(self, conn):
        # Same contract holds in the reverse direction — the edge is
        # directionless mutex-less.
        target, _ = self._stage(conn, blk_item_id=2211, cand_item_id=2212)
        _add_dep_edge(
            conn, dependent=2211, blocking=2212,
            gate_point="coordination_only",
        )
        outcome = classify_overlap(
            conn,
            target_ids=[target],
            integration_target="main",
            phase="register",
            candidate_item_id=2212,
        )
        assert outcome is OverlapClassification.NONE

    def test_mixed_coordination_and_activation_yields_serial(self, conn):
        # Any non-coordination edge still serialises.
        target, _ = self._stage(conn, blk_item_id=2221, cand_item_id=2222)
        _add_dep_edge(
            conn, dependent=2222, blocking=2221,
            gate_point="coordination_only",
        )
        _add_dep_edge(
            conn, dependent=2222, blocking=2221,
            gate_point="activation",
        )
        outcome = classify_overlap(
            conn,
            target_ids=[target],
            integration_target="main",
            phase="register",
            candidate_item_id=2222,
        )
        assert outcome is OverlapClassification.SERIAL_VIA_DEPENDENCY

    def test_explicit_upstream_overrides_coordination_only(self, conn):
        # Operator-asserted serialisation wins regardless of the
        # dep-edge shape between the two items.
        target, blk_claim = self._stage(
            conn, blk_item_id=2231, cand_item_id=2232,
        )
        _add_dep_edge(
            conn, dependent=2232, blocking=2231,
            gate_point="coordination_only",
        )
        outcome = classify_overlap(
            conn,
            target_ids=[target],
            integration_target="main",
            phase="register",
            candidate_item_id=2232,
            upstream_claim_id=blk_claim,
        )
        assert outcome is OverlapClassification.SERIAL_VIA_DEPENDENCY


# Render-target pre-check tests live in
# test_path_claims_overlap_render.py to keep this file under the
# 350-line gate.
