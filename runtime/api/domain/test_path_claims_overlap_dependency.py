"""Directional dependency-graph awareness in :func:`classify_overlap`.

The classifier walks ``item_dependencies`` directionally:

* candidate→blocker non-coord edge → ``SERIAL_VIA_DEPENDENCY``
  (candidate is the DEPENDENT side; the candidate waits)
* blocker→candidate non-coord edge → ``NONE``
  (candidate is the BLOCKER side; the candidate is upstream and does
  not wait — the reverse-side caller serializes correctly)
* coordination_only edge in either direction → ``NONE``
* no edge, no upstream → ``INCOMPATIBLE``
* explicit upstream still wins regardless of dep-graph state
* active override permits serial classification
"""

from __future__ import annotations


import pytest

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
        "blocking_item TEXT NOT NULL, gate_point TEXT NOT NULL DEFAULT 'activation', "
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


class TestForwardDepEdge:
    def test_candidate_to_blocker_edge_yields_serial(self, conn):
        # Candidate item declares dep on blocker item.
        target = seed_target(conn, path_string="runtime/api/domain")
        blk_item = _seed_item(conn, item_id=2001)
        cand_item = _seed_item(conn, item_id=2002)
        _seed_active_claim(conn, item_id=blk_item, target_id=target)
        _add_dep_edge(conn, dependent=cand_item, blocking=blk_item)

        outcome = classify_overlap(
            conn,
            target_ids=[target],
            integration_target="main",
            phase="register",
            candidate_item_id=cand_item,
        )
        assert outcome is OverlapClassification.SERIAL_VIA_DEPENDENCY


class TestReverseDepEdge:
    def test_blocker_to_candidate_edge_yields_none(self, conn):
        # Directional contract: when the OTHER side declares a non-coord
        # dep on the candidate, the candidate is the BLOCKER (upstream)
        # and does not wait. The overlap is attested by the reverse
        # edge; classify_overlap returns NONE so the candidate may
        # register/activate freely. From the OTHER side's perspective
        # (passing the items in reversed roles), the same edge classifies
        # as SERIAL_VIA_DEPENDENCY and serializes correctly.
        target = seed_target(conn, path_string="runtime/api/domain")
        cand_item = _seed_item(conn, item_id=2003)
        blk_item = _seed_item(conn, item_id=2004)
        _seed_active_claim(conn, item_id=blk_item, target_id=target)
        _add_dep_edge(conn, dependent=blk_item, blocking=cand_item)

        outcome = classify_overlap(
            conn,
            target_ids=[target],
            integration_target="main",
            phase="register",
            candidate_item_id=cand_item,
        )
        assert outcome is OverlapClassification.NONE


class TestNoEdge:
    def test_no_edge_no_upstream_is_incompatible(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        blk_item = _seed_item(conn, item_id=2005)
        cand_item = _seed_item(conn, item_id=2006)
        _seed_active_claim(conn, item_id=blk_item, target_id=target)
        # No item_dependencies edge.
        _ensure_item_dependencies_table(conn)
        outcome = classify_overlap(
            conn,
            target_ids=[target],
            integration_target="main",
            phase="register",
            candidate_item_id=cand_item,
        )
        assert outcome is OverlapClassification.INCOMPATIBLE


class TestExplicitUpstream:
    def test_explicit_upstream_still_wins(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        blk_item = _seed_item(conn, item_id=2007)
        cand_item = _seed_item(conn, item_id=2008)
        blk_claim = _seed_active_claim(
            conn, item_id=blk_item, target_id=target,
        )
        # No dep edge, but operator passes --upstream-claim-id explicitly.
        outcome = classify_overlap(
            conn,
            target_ids=[target],
            integration_target="main",
            phase="register",
            candidate_item_id=cand_item,
            upstream_claim_id=blk_claim,
        )
        assert outcome is OverlapClassification.SERIAL_VIA_DEPENDENCY


class TestCoordinationOnlyEdge:
    """Coordination-only edges yield ``NONE`` (parallel activation).

    Updated for the no-mutex contract: a ``coordination_only`` edge is
    the operator's explicit declaration that two items touch overlapping
    files but no path-claim serialisation is required. The classifier
    treats the pair as compatible at registration time; any same-hunk
    conflict surfaces as a normal git merge conflict at PR-merge time.
    Tests covering the new contract end-to-end live alongside the
    overlap classifier in ``test_path_claims_overlap.py::
    TestCoordinationOnlySemantics``.
    """

    def _stage(self, conn, base):
        target = seed_target(conn, path_string="runtime/api/domain")
        blk_item = _seed_item(conn, item_id=base)
        cand_item = _seed_item(conn, item_id=base + 1)
        _seed_active_claim(conn, item_id=blk_item, target_id=target)
        return target, blk_item, cand_item

    def _classify(self, conn, *, target, cand_item):
        return classify_overlap(
            conn, target_ids=[target], integration_target="main",
            phase="register", candidate_item_id=cand_item,
        )

    def test_classify_overlap_parallel_for_coordination_only(self, conn):
        # Coordination-only edge in either direction yields ``NONE``;
        # both claims may register and activate concurrently.
        target, blk_item, cand_item = self._stage(conn, 2101)
        _add_dep_edge(
            conn, dependent=cand_item, blocking=blk_item,
            gate_point="coordination_only",
        )
        assert self._classify(conn, target=target, cand_item=cand_item) is (
            OverlapClassification.NONE
        )

    def test_classify_overlap_incompatible_without_edge(self, conn):
        # Safety property preserved: without any ``item_dependencies``
        # row, the same fixture still classifies as INCOMPATIBLE.
        target, _, cand_item = self._stage(conn, 2103)
        _ensure_item_dependencies_table(conn)
        assert self._classify(conn, target=target, cand_item=cand_item) is (
            OverlapClassification.INCOMPATIBLE
        )


class TestOverridePermits:
    def test_active_override_yields_serial(self, conn, monkeypatch):
        # An active override on the pair permits serial.
        target = seed_target(conn, path_string="runtime/api/domain")
        blk_item = _seed_item(conn, item_id=2009)
        cand_item = _seed_item(conn, item_id=2010)
        blk_claim = _seed_active_claim(
            conn, item_id=blk_item, target_id=target,
        )
        # Stage a candidate planned claim so exclude_claim_id is meaningful.
        actor = local_human(conn)
        cur = conn.execute(
            "INSERT INTO path_claims "
            "(state, mode, actor_id, item_id, integration_target, registered_at) "
            "VALUES ('planned', 'exclusive', %s, %s, 'main', "
            "'2026-05-01T00:00:00Z') RETURNING id",
            (actor, cand_item),
        )
        cand_claim = int(cur.fetchone()[0])
        conn.execute(
            "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
            "VALUES (%s, %s, '2026-05-01T00:00:00Z')",
            (cand_claim, target),
        )
        conn.commit()

        # Stub is_active_override to return True for our pair.
        from yoke_core.domain import path_claims_overlap as _overlap_module
        from yoke_core.domain import path_claims_override as _override

        def _stub(conn, *, path_claim_id, blocking_claim_id):
            return path_claim_id == cand_claim and blocking_claim_id == blk_claim

        monkeypatch.setattr(_override, "is_active_override", _stub)

        outcome = classify_overlap(
            conn,
            target_ids=[target],
            integration_target="main",
            phase="register",
            exclude_claim_id=cand_claim,
            candidate_item_id=cand_item,
        )
        assert outcome is OverlapClassification.SERIAL_VIA_DEPENDENCY
