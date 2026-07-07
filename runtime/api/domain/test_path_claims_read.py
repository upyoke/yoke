"""Coverage for the read-API projections."""

from __future__ import annotations

import pytest

from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    SNAP,
    conn,
    local_human,
    seed_target,
)
from yoke_core.domain.path_claims import activate, register
from yoke_core.domain.path_claims_read import (
    claim_projection,
    cross_claim_conflicts,
    item_view,
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


def _add_edge(conn, *, dependent: int, blocking: int):
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
    conn.execute(
        "INSERT INTO item_dependencies (dependent_item, blocking_item, "
        "source, created_at) VALUES (%s, %s, 'test', '2026-05-01T00:00:00Z')",
        (f"YOK-{dependent}", f"YOK-{blocking}"),
    )
    conn.commit()


class TestClaimProjection:
    def test_projection_carries_paths_and_empty_amendments(self, conn):
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=2001)
        ta = seed_target(conn, path_string="runtime/api/domain")
        tb = seed_target(conn, path_string="docs/path-claims.md")
        cid = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[ta, tb],
            item_id=item_id,
        )
        view = claim_projection(conn, cid)
        assert view["state"] == "planned"
        assert view["target_ids"] == [ta, tb]
        assert view["declared_paths"] == [
            "runtime/api/domain",
            "docs/path-claims.md",
        ]
        assert view["amendments"] == []
        assert view["blocking_conflicts"] == []

    def test_projection_includes_amendments_when_present(self, conn):
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=2002)
        ta = seed_target(conn, path_string="runtime/api/domain")
        cid = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[ta],
            item_id=item_id,
        )
        conn.execute(
            "INSERT INTO path_claim_amendments "
            "(claim_id, amendment_kind, payload, reason, amended_at) "
            "VALUES (%s, 'widen', '{\"added\":[1]}', 'follow-up', "
            "'2026-05-01T00:01:00Z')",
            (cid,),
        )
        conn.commit()
        view = claim_projection(conn, cid)
        assert len(view["amendments"]) == 1
        assert view["amendments"][0]["amendment_kind"] == "widen"
        assert view["amendments"][0]["reason"] == "follow-up"

    def test_projection_surfaces_blocking_conflict(self, conn):
        actor = local_human(conn)
        item_a = _seed_item(conn, item_id=3001)
        item_b = _seed_item(conn, item_id=3002)
        target = seed_target(conn, path_string="runtime/api/domain")
        first = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
            item_id=item_a,
        )
        activate(conn, claim_id=first, base_commit_sha=SNAP)
        second = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
            item_id=item_b,
            upstream_claim_id=first,
        )
        # The blocked claim should report `first` as a blocking conflict.
        view = claim_projection(conn, second)
        assert view["state"] == "blocked"
        ids = [c["claim_id"] for c in view["blocking_conflicts"]]
        assert first in ids

    def test_projection_hides_serial_dependency_for_active_claim(self, conn):
        actor = local_human(conn)
        item_a = _seed_item(conn, item_id=3101)
        item_b = _seed_item(conn, item_id=3102)
        target_a = seed_target(conn, path_string="runtime/api/domain")
        target_b = seed_target(conn, path_string="docs")
        first = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target_a],
            item_id=item_a,
        )
        activate(conn, claim_id=first, base_commit_sha=SNAP)
        second = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target_b],
            item_id=item_b,
        )
        conn.execute(
            "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
            "VALUES (%s, %s, '2026-05-01T00:00:00Z')",
            (second, target_a),
        )
        _add_edge(conn, dependent=item_b, blocking=item_a)

        view = claim_projection(conn, first)

        assert view["state"] == "active"
        assert view["blocking_conflicts"] == []


class TestItemView:
    def test_item_view_returns_all_claims_for_item(self, conn):
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=4001)
        ta = seed_target(conn, path_string="runtime/api/domain")
        tb = seed_target(conn, path_string="docs/path-claims.md")
        cid_a = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[ta], item_id=item_id,
        )
        cid_b = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[tb], item_id=item_id,
        )
        rows = item_view(conn, item_id)
        assert sorted(r["id"] for r in rows) == sorted([cid_a, cid_b])
        assert all("declared_paths" in r for r in rows)

    def test_item_view_filters_by_state(self, conn):
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=4002)
        target = seed_target(conn, path_string="runtime/api/domain")
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_id,
        )
        rows = item_view(conn, item_id, states=["active"])
        assert rows == []

    def test_item_view_for_unknown_item_returns_empty(self, conn):
        assert item_view(conn, 999_999) == []


class TestCrossClaimConflicts:
    def test_conflicts_reports_one_pair_per_overlap(self, conn):
        actor = local_human(conn)
        item_a = _seed_item(conn, item_id=5001)
        item_b = _seed_item(conn, item_id=5002)
        target = seed_target(conn, path_string="runtime/api/domain")
        first = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_a,
        )
        activate(conn, claim_id=first, base_commit_sha=SNAP)
        second = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_b,
            upstream_claim_id=first,
        )
        conflicts = cross_claim_conflicts(conn)
        assert len(conflicts) == 1
        pair = conflicts[0]
        assert pair["integration_target"] == "main"
        ids = sorted([pair["claim_a"]["claim_id"], pair["claim_b"]["claim_id"]])
        assert ids == sorted([first, second])
        assert "amend" in pair["recommended_remediation"]

    def test_conflicts_filters_by_integration_target(self, conn):
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=5003)
        target = seed_target(conn, path_string="runtime/api/domain")
        first = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_id,
        )
        activate(conn, claim_id=first, base_commit_sha=SNAP)
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_id,
            upstream_claim_id=first,
        )
        # Different integration target — same target, but cross-target
        # claims are independent door locks per the overlap classifier.
        conflicts_main = cross_claim_conflicts(conn, integration_target="main")
        conflicts_release = cross_claim_conflicts(
            conn, integration_target="release/2026.05"
        )
        assert len(conflicts_main) >= 1
        assert conflicts_release == []

    def test_conflicts_returns_empty_when_no_overlap(self, conn):
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=5004)
        ta = seed_target(conn, path_string="runtime/api/domain")
        tb = seed_target(conn, path_string="docs/path-claims.md")
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[ta], item_id=item_id,
        )
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[tb], item_id=item_id,
        )
        assert cross_claim_conflicts(conn) == []
