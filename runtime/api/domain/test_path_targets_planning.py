"""Tests for planned-target creation, materialization, and snapshot reuse.

Covers AC-5/6/7/8/9/10/16 from the spec: schema columns
present, backfill, exact-future-path planning with ancestor chain,
snapshot-time materialization preserving claim identity, abandon +
re-plan, and the no-parallel-table invariant.
"""

from __future__ import annotations

from typing import Any

import pytest

from yoke_core.domain._path_claims_test_helpers import conn  # noqa: F401
from yoke_core.domain.path_registry import KIND_DIRECTORY, KIND_FILE
from yoke_core.domain.path_claims_resolve import (
    resolve_or_plan_paths_to_target_ids,
)
from yoke_core.domain.path_targets_materialization import (
    abandon_planned_target,
    find_planned_match,
    materialize_planned_target,
    plan_path_target,
)
from yoke_core.domain.schema_common import _get_columns, _table_exists


def _path_targets_columns(conn: Any) -> set[str]:
    return set(_get_columns(conn, "path_targets"))


class TestSchema:
    def test_path_targets_carries_materialization_columns(self, conn):
        cols = _path_targets_columns(conn)
        assert "materialization_state" in cols
        assert "materialization_updated_at" in cols
        assert "planned_by_item_id" in cols
        assert "planned_by_claim_id" in cols

    def test_no_parallel_future_targets_table(self, conn):
        assert not _table_exists(
            conn, "path_claim_future_targets"
        ), "AC-16: no parallel future-target table"

    def test_default_materialization_state_observed(self, conn):
        row = conn.execute(
            "INSERT INTO path_targets "
            "(project_id, kind, path_string, generation, created_at) "
            "VALUES (1, 'file', 'observed.py', 1, "
            "'2026-05-01T00:00:00Z') RETURNING id"
        ).fetchone()
        target_id = int(row[0])
        row = conn.execute(
            "SELECT materialization_state FROM path_targets WHERE id = %s",
            (target_id,),
        ).fetchone()
        assert row["materialization_state"] == "observed"


class TestPlanPathTarget:
    def test_plans_leaf_and_chains_planned_ancestors(self, conn):
        leaf = plan_path_target(
            conn,
            project_id=1,
            path_string="runtime/api/domain/new_module.py",
            kind=KIND_FILE,
            item_id=999,
        )
        rows = conn.execute(
            "SELECT path_string, kind, materialization_state, "
            "       parent_target_id, planned_by_item_id "
            "FROM path_targets ORDER BY id"
        ).fetchall()
        path_strings = [r["path_string"] for r in rows]
        # Snapshot fixture seeded none, helper minted root + 3 dirs + leaf.
        assert "" in path_strings
        assert "runtime" in path_strings
        assert "runtime/api/domain/new_module.py" in path_strings
        leaf_row = conn.execute(
            "SELECT materialization_state, planned_by_item_id "
            "FROM path_targets WHERE id = %s", (leaf,),
        ).fetchone()
        assert leaf_row["materialization_state"] == "planned"
        assert leaf_row["planned_by_item_id"] == 999

    def test_reuses_observed_row_without_state_change(self, conn):
        row = conn.execute(
            "INSERT INTO path_targets "
            "(project_id, kind, path_string, generation, created_at, "
            "materialization_state, materialization_updated_at) "
            "VALUES (1, 'file', 'existing.py', 1, "
            "'2026-05-01T00:00:00Z', 'observed', "
            "'2026-05-01T00:00:00Z') RETURNING id"
        ).fetchone()
        existing_id = int(row[0])
        reused = plan_path_target(
            conn, project_id=1,
            path_string="existing.py", kind=KIND_FILE, item_id=1,
        )
        assert reused == existing_id
        state = conn.execute(
            "SELECT materialization_state FROM path_targets WHERE id = %s",
            (reused,),
        ).fetchone()["materialization_state"]
        assert state == "observed"

    def test_re_plans_abandoned_row_without_minting_new_generation(self, conn):
        first = plan_path_target(
            conn, project_id=1,
            path_string="runtime/x.py", kind=KIND_FILE, item_id=1,
        )
        assert abandon_planned_target(
            conn, target_id=first, reason="superseded",
        ) is True
        replanned = plan_path_target(
            conn, project_id=1,
            path_string="runtime/x.py", kind=KIND_FILE, item_id=2,
        )
        assert replanned == first
        state = conn.execute(
            "SELECT materialization_state FROM path_targets WHERE id = %s",
            (first,),
        ).fetchone()["materialization_state"]
        assert state == "planned"

    def test_future_resolver_replans_abandoned_row(self, conn):
        first = plan_path_target(
            conn, project_id=1,
            path_string="runtime/y.py", kind=KIND_FILE, item_id=1,
        )
        assert abandon_planned_target(
            conn, target_id=first, reason="superseded",
        ) is True
        resolved = resolve_or_plan_paths_to_target_ids(
            conn,
            1,
            ["runtime/y.py"],
            item_id=2,
        )
        assert resolved == [first]
        state = conn.execute(
            "SELECT materialization_state FROM path_targets WHERE id = %s",
            (first,),
        ).fetchone()["materialization_state"]
        assert state == "planned"

    def test_rejects_non_file_or_directory_kind(self, conn):
        with pytest.raises(ValueError):
            plan_path_target(
                conn, project_id=1,
                path_string="foo", kind="symlink",
            )

    def test_rejects_absolute_path_string(self, conn):
        with pytest.raises(ValueError, match="project-relative"):
            plan_path_target(
                conn,
                project_id=1,
                path_string="/tmp/spec.txt",
                kind=KIND_FILE,
            )

    def test_no_duplicate_identity_across_states(self, conn):
        plan_path_target(
            conn, project_id=1,
            path_string="dup.py", kind=KIND_FILE,
        )
        # Re-planning the same identity reuses the row.
        plan_path_target(
            conn, project_id=1,
            path_string="dup.py", kind=KIND_FILE,
        )
        rows = conn.execute(
            "SELECT COUNT(*) FROM path_targets "
            "WHERE project_id=1 AND path_string='dup.py'"
        ).fetchone()[0]
        assert rows == 1, "AC-10: no duplicate identity for same path/generation"


class TestMaterialization:
    def test_find_planned_match_matches_exact_identity(self, conn):
        leaf = plan_path_target(
            conn, project_id=1,
            path_string="a/b/c.py", kind=KIND_FILE, item_id=1,
        )
        parent = conn.execute(
            "SELECT id FROM path_targets WHERE path_string='a/b'"
        ).fetchone()[0]
        match = find_planned_match(
            conn, project_id=1,
            path_string="a/b/c.py", kind=KIND_FILE,
            parent_target_id=parent,
        )
        assert match == leaf

    def test_find_planned_match_rejects_kind_mismatch(self, conn):
        leaf = plan_path_target(
            conn, project_id=1,
            path_string="a/b/c.py", kind=KIND_FILE, item_id=1,
        )
        parent = conn.execute(
            "SELECT id FROM path_targets WHERE path_string='a/b'"
        ).fetchone()[0]
        match = find_planned_match(
            conn, project_id=1,
            path_string="a/b/c.py", kind=KIND_DIRECTORY,
            parent_target_id=parent,
        )
        assert match is None

    def test_materialize_flips_state_and_returns_true(self, conn):
        tid = plan_path_target(
            conn, project_id=1,
            path_string="m.py", kind=KIND_FILE, item_id=1,
        )
        flipped = materialize_planned_target(
            conn, target_id=tid, commit_sha="sha1",
        )
        assert flipped is True
        state = conn.execute(
            "SELECT materialization_state FROM path_targets WHERE id=%s",
            (tid,),
        ).fetchone()["materialization_state"]
        assert state == "observed"

    def test_materialize_idempotent_on_observed_row(self, conn):
        tid = plan_path_target(
            conn, project_id=1,
            path_string="i.py", kind=KIND_FILE, item_id=1,
        )
        materialize_planned_target(
            conn, target_id=tid, commit_sha="sha1",
        )
        flipped = materialize_planned_target(
            conn, target_id=tid, commit_sha="sha2",
        )
        assert flipped is False

    def test_planned_target_with_zero_snapshot_entries_is_valid(self, conn):
        tid = plan_path_target(
            conn, project_id=1,
            path_string="future.py", kind=KIND_FILE, item_id=1,
        )
        n = conn.execute(
            "SELECT COUNT(*) FROM path_snapshot_entries WHERE target_id=%s",
            (tid,),
        ).fetchone()[0]
        assert n == 0, "AC-9: planned targets need not appear in any snapshot"
