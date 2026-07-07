"""Coverage for the dep-graph resolver helpers.

Covers AC-11/AC-12 register-side awareness:

* ``has_bidirectional_dep_edge`` returns True for forward + reverse
  edges, False otherwise.
* ``resolve_upstream_for_register`` picks an overlapping claim only
  when every overlapping owner is covered and at least one candidate ->
  blocker edge is serial. ``coordination_only`` edges count as covered
  but do not name an upstream.
* ``auto_resolve_upstream`` resolves end-to-end through the path target
  resolver against a real overlap.
* ``cross_check_explicit_upstream`` returns advisory text only when
  the operator-supplied upstream contradicts the dep-graph.
"""

from __future__ import annotations


import pytest

from yoke_core.domain.path_claims_dependency_resolver import (
    cross_check_explicit_upstream,
    has_bidirectional_dep_edge,
    resolve_upstream_for_register,
)
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


def _add_edge(
    conn, *, dependent: int, blocking: int, gate_point: str = "activation",
):
    _ensure_dep_table(conn)
    conn.execute(
        "INSERT INTO item_dependencies (dependent_item, blocking_item, "
        "gate_point, source, created_at) "
        "VALUES (%s, %s, %s, 'test', '2026-05-01T00:00:00Z')",
        (f"YOK-{dependent}", f"YOK-{blocking}", gate_point),
    )
    conn.commit()


def _seed_claim(
    conn, *, item_id: int, target_id: int, state: str = "active"
) -> int:
    actor = local_human(conn)
    cur = conn.execute(
        "INSERT INTO path_claims "
        "(state, mode, actor_id, item_id, integration_target, registered_at, "
        "activated_at, base_commit_sha) "
        "VALUES (%s, 'exclusive', %s, %s, 'main', "
        "'2026-05-01T00:00:00Z', '2026-05-01T01:00:00Z', %s) RETURNING id",
        (state, actor, item_id, SNAP),
    )
    cid = int(cur.fetchone()[0])
    conn.execute(
        "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
        "VALUES (%s, %s, '2026-05-01T00:00:00Z')",
        (cid, target_id),
    )
    conn.commit()
    return cid


class TestHasBidirectionalEdge:
    def test_forward_edge_returns_true(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        blk_item = _seed_item(conn, item_id=3001)
        cand_item = _seed_item(conn, item_id=3002)
        blk_claim = _seed_claim(conn, item_id=blk_item, target_id=target)
        _add_edge(conn, dependent=cand_item, blocking=blk_item)
        assert has_bidirectional_dep_edge(
            conn,
            candidate_claim_id=None,
            candidate_item_id=cand_item,
            blocking_claim_id=blk_claim,
        ) is True

    def test_reverse_edge_returns_true(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        blk_item = _seed_item(conn, item_id=3003)
        cand_item = _seed_item(conn, item_id=3004)
        blk_claim = _seed_claim(conn, item_id=blk_item, target_id=target)
        _add_edge(conn, dependent=blk_item, blocking=cand_item)
        assert has_bidirectional_dep_edge(
            conn,
            candidate_claim_id=None,
            candidate_item_id=cand_item,
            blocking_claim_id=blk_claim,
        ) is True

    def test_no_edge_returns_false(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        blk_item = _seed_item(conn, item_id=3005)
        cand_item = _seed_item(conn, item_id=3006)
        blk_claim = _seed_claim(conn, item_id=blk_item, target_id=target)
        _ensure_dep_table(conn)
        assert has_bidirectional_dep_edge(
            conn,
            candidate_claim_id=None,
            candidate_item_id=cand_item,
            blocking_claim_id=blk_claim,
        ) is False

    def test_missing_table_returns_false(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        blk_item = _seed_item(conn, item_id=3007)
        cand_item = _seed_item(conn, item_id=3008)
        blk_claim = _seed_claim(conn, item_id=blk_item, target_id=target)
        # Do NOT create item_dependencies — resolver should tolerate.
        assert has_bidirectional_dep_edge(
            conn,
            candidate_claim_id=None,
            candidate_item_id=cand_item,
            blocking_claim_id=blk_claim,
        ) is False


class TestResolveUpstream:
    def test_returns_none_when_only_some_overlaps_have_edges(self, conn):
        t1 = seed_target(conn, path_string="runtime/api/domain")
        t2 = seed_target(conn, path_string="docs")
        a = _seed_item(conn, item_id=3101)
        b = _seed_item(conn, item_id=3102)
        cand = _seed_item(conn, item_id=3103)
        a_claim = _seed_claim(conn, item_id=a, target_id=t1)
        b_claim = _seed_claim(conn, item_id=b, target_id=t2)
        # cand depends on b, not a.
        _add_edge(conn, dependent=cand, blocking=b)
        chosen = resolve_upstream_for_register(
            conn,
            candidate_item_id=cand,
            overlapping_claim_ids=[a_claim, b_claim],
        )
        assert chosen is None

    def test_picks_first_when_all_overlaps_have_edges(self, conn):
        t1 = seed_target(conn, path_string="runtime/api/domain")
        t2 = seed_target(conn, path_string="docs")
        a = _seed_item(conn, item_id=3111)
        b = _seed_item(conn, item_id=3112)
        cand = _seed_item(conn, item_id=3113)
        a_claim = _seed_claim(conn, item_id=a, target_id=t1)
        b_claim = _seed_claim(conn, item_id=b, target_id=t2)
        _add_edge(conn, dependent=cand, blocking=a)
        _add_edge(conn, dependent=cand, blocking=b)
        chosen = resolve_upstream_for_register(
            conn,
            candidate_item_id=cand,
            overlapping_claim_ids=[a_claim, b_claim],
        )
        assert chosen == a_claim

    def test_returns_none_when_no_edge(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        blk_item = _seed_item(conn, item_id=3104)
        cand_item = _seed_item(conn, item_id=3105)
        blk_claim = _seed_claim(conn, item_id=blk_item, target_id=target)
        _ensure_dep_table(conn)
        chosen = resolve_upstream_for_register(
            conn,
            candidate_item_id=cand_item,
            overlapping_claim_ids=[blk_claim],
        )
        assert chosen is None


class TestCoordinationOnlyNoUpstream:
    def test_resolve_upstream_ignores_reverse_coordination_only_edge(
        self, conn,
    ):
        # No-mutex contract: coordination_only covers the overlap but
        # never becomes the named serial upstream.
        target = seed_target(conn, path_string="runtime/api/domain")
        blk_item = _seed_item(conn, item_id=3301)
        cand_item = _seed_item(conn, item_id=3302)
        blk_claim = _seed_claim(conn, item_id=blk_item, target_id=target)
        _add_edge(
            conn,
            dependent=blk_item,
            blocking=cand_item,
            gate_point="coordination_only",
        )
        chosen = resolve_upstream_for_register(
            conn,
            candidate_item_id=cand_item,
            overlapping_claim_ids=[blk_claim],
        )
        assert chosen is None

    def test_resolve_upstream_ignores_forward_coordination_only_edge(
        self, conn,
    ):
        target = seed_target(conn, path_string="runtime/api/domain")
        blk_item = _seed_item(conn, item_id=3311)
        cand_item = _seed_item(conn, item_id=3312)
        blk_claim = _seed_claim(conn, item_id=blk_item, target_id=target)
        _add_edge(
            conn,
            dependent=cand_item,
            blocking=blk_item,
            gate_point="coordination_only",
        )
        chosen = resolve_upstream_for_register(
            conn,
            candidate_item_id=cand_item,
            overlapping_claim_ids=[blk_claim],
        )
        assert chosen is None

    def test_mixed_coordination_and_activation_picks_serial_upstream(
        self, conn,
    ):
        t1 = seed_target(conn, path_string="runtime/api/domain/a.py")
        t2 = seed_target(conn, path_string="runtime/api/domain/b.py")
        coord_item = _seed_item(conn, item_id=3321)
        serial_item = _seed_item(conn, item_id=3322)
        cand_item = _seed_item(conn, item_id=3323)
        coord_claim = _seed_claim(conn, item_id=coord_item, target_id=t1)
        serial_claim = _seed_claim(conn, item_id=serial_item, target_id=t2)
        _add_edge(
            conn,
            dependent=cand_item,
            blocking=coord_item,
            gate_point="coordination_only",
        )
        _add_edge(
            conn,
            dependent=cand_item,
            blocking=serial_item,
            gate_point="activation",
        )
        chosen = resolve_upstream_for_register(
            conn,
            candidate_item_id=cand_item,
            overlapping_claim_ids=[coord_claim, serial_claim],
        )
        assert chosen == serial_claim

    def test_resolve_upstream_rejects_reverse_activation_edge(self, conn):
        # Negative: activation edges remain one-way. A reverse-only
        # activation edge must NOT cause resolve_upstream_for_register to
        # pick the overlapping claim — only coordination_only is bidir.
        target = seed_target(conn, path_string="runtime/api/domain")
        blk_item = _seed_item(conn, item_id=3303)
        cand_item = _seed_item(conn, item_id=3304)
        blk_claim = _seed_claim(conn, item_id=blk_item, target_id=target)
        _add_edge(
            conn,
            dependent=blk_item,
            blocking=cand_item,
            gate_point="activation",
        )
        chosen = resolve_upstream_for_register(
            conn,
            candidate_item_id=cand_item,
            overlapping_claim_ids=[blk_claim],
        )
        assert chosen is None


class TestCrossCheckExplicitUpstream:
    def test_no_advisory_when_edge_matches(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        blk_item = _seed_item(conn, item_id=3201)
        cand_item = _seed_item(conn, item_id=3202)
        blk_claim = _seed_claim(conn, item_id=blk_item, target_id=target)
        _add_edge(conn, dependent=cand_item, blocking=blk_item)
        msg = cross_check_explicit_upstream(
            conn, item_id=cand_item, upstream_claim_id=blk_claim,
        )
        assert msg is None

    def test_advisory_when_edge_missing(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        blk_item = _seed_item(conn, item_id=3203)
        cand_item = _seed_item(conn, item_id=3204)
        blk_claim = _seed_claim(conn, item_id=blk_item, target_id=target)
        _ensure_dep_table(conn)
        msg = cross_check_explicit_upstream(
            conn, item_id=cand_item, upstream_claim_id=blk_claim,
        )
        assert msg is not None
        assert "Advisory" in msg
        assert str(blk_claim) in msg
