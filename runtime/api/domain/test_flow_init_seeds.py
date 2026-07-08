"""Seed-flow shape tests: every seeded flow validates against the live vocabulary."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_core.domain.flow_init import _SEED_FLOWS, cmd_init as flow_cmd_init
from yoke_core.domain.flow_validation import VALID_EXECUTORS, validate_stages


class TestSeedFlows:
    def test_every_seed_flow_validates(self):
        for flow in _SEED_FLOWS:
            validate_stages(flow["stages"])  # raises on invalid

    def test_seed_ids_are_the_cloud_runtime_set(self):
        ids = {flow["id"] for flow in _SEED_FLOWS}
        assert ids == {
            "yoke-internal",
            "yoke-prod-release",
            "yoke-stage-release",
            "yoke-ephemeral-deploy",
            "buzz-prod-release",
            "buzz-prod-hotfix",
            "buzz-internal",
        }

    def test_every_seed_stage_executor_is_in_the_live_vocabulary(self):
        for flow in _SEED_FLOWS:
            for stage in json.loads(flow["stages"]):
                if "executor" in stage:
                    assert stage["executor"] in VALID_EXECUTORS

    def test_prod_release_carries_governed_migration_and_core_deploy(self):
        flow = next(f for f in _SEED_FLOWS if f["id"] == "yoke-prod-release")
        stages = json.loads(flow["stages"])
        assert stages[0] == {
            "kind": "migration_apply",
            "model_name": "primary",
            "lifecycle_phase": "implementing",
        }
        executors = [s.get("executor") for s in stages if "executor" in s]
        assert executors == [
            "auto",
            "environment-activate",
            "core-container-deploy",
            "health-check",
            "github-actions-workflow",
            "auto",
        ]
        assert flow["target_env"] == "prod"
        health = next(s for s in stages if s.get("executor") == "health-check")
        assert "url" not in health  # env-resolved, never hardcoded
        publish = next(
            s for s in stages if s.get("name") == "distribution-publish"
        )
        assert publish["workflow"] == "yoke-distribution-publish.yml"
        assert publish["ref"] == "main"
        assert publish["inputs"] == {
            "channel": "stable",
            "target_env": "prod",
            "source_sha": "{head_sha}",
        }
        assert publish["reconcile_by_head_sha"] is False
        assert publish["qa_kind"] == "distribution_publish"

    def test_stage_release_skips_governed_migration(self):
        flow = next(
            f for f in _SEED_FLOWS if f["id"] == "yoke-stage-release"
        )
        stages = json.loads(flow["stages"])
        assert all(s.get("kind") != "migration_apply" for s in stages)
        assert flow["target_env"] == "stage"
        publish = next(
            s for s in stages if s.get("name") == "distribution-publish"
        )
        assert publish["workflow"] == "yoke-distribution-publish.yml"
        assert publish["ref"] == "stage"
        assert publish["inputs"] == {
            "channel": "latest",
            "target_env": "stage",
            "source_sha": "{head_sha}",
        }
        assert publish["reconcile_by_head_sha"] is False

    def test_ephemeral_flow_targets_ephemeral(self):
        flow = next(
            f for f in _SEED_FLOWS if f["id"] == "yoke-ephemeral-deploy"
        )
        stages = json.loads(flow["stages"])
        assert any(s.get("executor") == "ephemeral-deploy" for s in stages)
        assert flow["target_env"] == "ephemeral"

    def test_ephemeral_flow_carries_no_merged_stage(self):
        """Preview flows deploy unmerged worktree branches; a 'merged'
        stage label would misrepresent the tier's gate semantics."""
        flow = next(
            f for f in _SEED_FLOWS if f["id"] == "yoke-ephemeral-deploy"
        )
        stages = json.loads(flow["stages"])
        assert [s["name"] for s in stages] == ["ephemeral-deploy", "complete"]


class TestSeedFlowsRequireProjects:
    """Flow rows seed only for projects present in the universe.

    A fresh universe has no project rows, so ``cmd_init`` creates the
    table and view but inserts no flows; once the matching projects
    exist (any numeric id — resolution is by slug), the same init seeds
    their flows against the live ids.
    """

    def _init_min_schema(self, conn) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS projects ("
            "id BIGINT PRIMARY KEY, slug TEXT NOT NULL UNIQUE, "
            "created_at TEXT)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS items "
            "(id BIGINT PRIMARY KEY, status TEXT)"
        )
        conn.commit()

    def test_empty_universe_seeds_no_flows_then_projects_bring_them(
        self, tmp_path: Path
    ):
        from yoke_core.domain import db_backend
        from runtime.api.fixtures.file_test_db import init_test_db

        def _apply() -> None:
            conn = db_backend.connect()
            try:
                self._init_min_schema(conn)
            finally:
                conn.close()

        with init_test_db(tmp_path, apply_schema=_apply):
            conn = db_backend.connect()
            try:
                flow_cmd_init(conn)
                count = conn.execute(
                    "SELECT COUNT(*) FROM deployment_flows"
                ).fetchone()[0]
                assert int(count) == 0

                # Non-baseline ids prove slug resolution, not assumed ids.
                conn.execute(
                    "INSERT INTO projects (id, slug) VALUES (41, 'yoke')"
                )
                conn.execute(
                    "INSERT INTO projects (id, slug) VALUES (42, 'buzz')"
                )
                conn.commit()
                flow_cmd_init(conn)
                rows = conn.execute(
                    "SELECT id, project_id FROM deployment_flows ORDER BY id"
                ).fetchall()
                by_id = {str(r[0]): int(r[1]) for r in rows}
                assert set(by_id) == {f["id"] for f in _SEED_FLOWS}
                for flow in _SEED_FLOWS:
                    expected = 41 if flow["project"] == "yoke" else 42
                    assert by_id[str(flow["id"])] == expected
            finally:
                conn.close()
