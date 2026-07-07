"""Ancestor/descendant overlap detection across planned + observed.

Covers AC-11, AC-14 from the spec: claims on a directory
collide with claims on files inside it (and vice versa) regardless of
which side is planned vs observed; renames work when the source is
observed and the destination is planned; exception claims never
participate in overlap.
"""

from __future__ import annotations

import pytest

from yoke_core.domain._path_claims_test_helpers import (
    conn,  # noqa: F401
    local_human,
)
from yoke_core.domain.path_claims import (
    IncompatibleOverlap,
    register,
)
from yoke_core.domain.path_claims_exception import register_exception
from yoke_core.domain.path_claims_overlap import (
    OverlapClassification,
    classify_overlap,
    expand_lineage,
)
from yoke_core.domain.path_registry import KIND_FILE
from yoke_core.domain.path_targets_planning import plan_path_target


class TestExpandLineage:
    def test_includes_ancestors_and_descendants(self, conn):
        leaf = plan_path_target(
            conn, project_id=1,
            path_string="a/b/c.py", kind=KIND_FILE, item_id=1,
        )
        expanded = expand_lineage(conn, [leaf])
        rows = conn.execute(
            "SELECT id, path_string FROM path_targets WHERE id IN ("
            + ",".join("%s" for _ in expanded) + ")",
            tuple(expanded),
        ).fetchall()
        paths = {r["path_string"] for r in rows}
        assert {"", "a", "a/b", "a/b/c.py"}.issubset(paths)

    def test_expands_many_targets_with_one_graph_scan(self, conn):
        leaves = [
            plan_path_target(
                conn, project_id=1,
                path_string=f"bulk/path_{idx}.py", kind=KIND_FILE,
                item_id=1,
            )
            for idx in range(120)
        ]

        class CountingConn:
            def __init__(self, inner):
                self.inner = inner
                self.graph_scans = 0

            def execute(self, sql, *args, **kwargs):
                if "SELECT id, parent_target_id FROM path_targets" in sql:
                    self.graph_scans += 1
                if "WITH RECURSIVE" in sql:
                    raise AssertionError("expand_lineage used recursive query")
                return self.inner.execute(sql, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(self.inner, name)

        wrapped = CountingConn(conn)
        expanded = expand_lineage(wrapped, leaves)

        assert wrapped.graph_scans == 1
        assert set(leaves).issubset(set(expanded))


class TestRegisterDescendantConflict:
    def test_directory_then_file_conflicts(self, conn):
        actor = local_human(conn)
        leaf = plan_path_target(
            conn, project_id=1,
            path_string="a/b/c.py", kind=KIND_FILE, item_id=1,
        )
        ab = conn.execute(
            "SELECT id FROM path_targets WHERE path_string='a/b'"
        ).fetchone()[0]
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[ab], item_id=1,
        )
        with pytest.raises(IncompatibleOverlap):
            register(
                conn, actor_id=actor, integration_target="main",
                target_ids=[leaf], item_id=2,
            )

    def test_file_then_directory_conflicts(self, conn):
        actor = local_human(conn)
        leaf = plan_path_target(
            conn, project_id=1,
            path_string="a/b/c.py", kind=KIND_FILE, item_id=1,
        )
        ab = conn.execute(
            "SELECT id FROM path_targets WHERE path_string='a/b'"
        ).fetchone()[0]
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[leaf], item_id=1,
        )
        with pytest.raises(IncompatibleOverlap):
            register(
                conn, actor_id=actor, integration_target="main",
                target_ids=[ab], item_id=2,
            )

    def test_disjoint_subtrees_do_not_conflict(self, conn):
        actor = local_human(conn)
        a_file = plan_path_target(
            conn, project_id=1,
            path_string="a/x.py", kind=KIND_FILE, item_id=1,
        )
        b_file = plan_path_target(
            conn, project_id=1,
            path_string="b/y.py", kind=KIND_FILE, item_id=2,
        )
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[a_file], item_id=1,
        )
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[b_file], item_id=2,
        )

    def test_exception_claim_never_conflicts(self, conn):
        actor = local_human(conn)
        # Exception lands first — should not block subsequent real claim.
        register_exception(
            conn, actor_id=actor, integration_target="main",
            target_ids=[], exception_reason="meta", item_id=10,
        )
        leaf = plan_path_target(
            conn, project_id=1,
            path_string="real.py", kind=KIND_FILE, item_id=11,
        )
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[leaf], item_id=11,
        )

    def test_classify_overlap_returns_incompatible_via_descendant(self, conn):
        actor = local_human(conn)
        plan_path_target(
            conn, project_id=1,
            path_string="x/y/z.py", kind=KIND_FILE, item_id=1,
        )
        xy = conn.execute(
            "SELECT id FROM path_targets WHERE path_string='x/y'"
        ).fetchone()[0]
        leaf = conn.execute(
            "SELECT id FROM path_targets WHERE path_string='x/y/z.py'"
        ).fetchone()[0]
        # Register the directory claim first.
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[xy], item_id=1,
        )
        # Classifier called directly with the leaf set.
        result = classify_overlap(
            conn, target_ids=[leaf], integration_target="main",
        )
        assert result is OverlapClassification.INCOMPATIBLE


class TestRenameCoverage:
    def test_observed_source_plus_planned_destination_can_co_exist(self, conn):
        """AC-14: a rename plan claims observed source + planned destination."""
        actor = local_human(conn)
        # Seed an observed source row directly.
        cur = conn.execute(
            "INSERT INTO path_targets "
            "(project_id, kind, path_string, generation, created_at, "
            " materialization_state, materialization_updated_at) "
            "VALUES (1, 'file', 'old.py', 1, "
            "'2026-05-01T00:00:00Z', 'observed', '2026-05-01T00:00:00Z') "
            "RETURNING id"
        )
        old_id = cur.fetchone()[0]
        new_id = plan_path_target(
            conn, project_id=1,
            path_string="new.py", kind=KIND_FILE, item_id=1,
        )
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[old_id, new_id], item_id=1,
        )
        from yoke_core.domain.path_claims import get_claim
        claim = get_claim(conn, cid)
        assert sorted(claim["target_ids"]) == sorted([old_id, new_id])
