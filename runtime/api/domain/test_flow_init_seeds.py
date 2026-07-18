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
            "yoke-ephemeral-deploy",
            "yoke-hosted-production",
            "yoke-hosted-production-hotfix",
            "yoke-hosted-production-hotfix-no-ci-gate",
            "yoke-hosted-stage",
            "yoke-hosted-stage-no-ci-gate",
            "platform-production",
            "platform-production-independent",
            "platform-production-hotfix",
            "platform-stage",
            "buzz-production-release",
            "buzz-production-hotfix",
            "buzz-internal",
        }

    def test_every_seed_stage_executor_is_in_the_live_vocabulary(self):
        for flow in _SEED_FLOWS:
            for stage in json.loads(flow["stages"]):
                if "executor" in stage:
                    assert stage["executor"] in VALID_EXECUTORS

    def test_project_local_hosted_flows_cover_stage_production_and_hotfix(self):
        by_id = {flow["id"]: flow for flow in _SEED_FLOWS}
        expected = (
            (
                "yoke-hosted-stage-no-ci-gate", "yoke", ["stage"],
                "normal", True,
            ),
            (
                "yoke-hosted-production-hotfix-no-ci-gate", "yoke",
                ["production"], "hotfix", True,
            ),
            ("platform-stage", "platform", ["stage"], "normal", False),
            (
                "platform-production-independent", "platform", ["production"],
                "normal", False,
            ),
            (
                "platform-production-hotfix", "platform", ["production"],
                "hotfix", False,
            ),
        )
        for flow_id, project, environments, mode, is_bridge in expected:
            flow = by_id[flow_id]
            assert flow["project"] == project
            assert flow["status"] == "active"
            stages = [
                stage for stage in json.loads(flow["stages"])
                if stage.get("executor") == "github-actions-workflow"
            ]
            assert [
                stage["inputs"]["target_environment"] for stage in stages
            ] == environments
            for stage in stages:
                assert stage["inputs"]["release_mode"] == mode
                assert ("product_sha" in stage["inputs"]) is is_bridge
                assert ("platform_ref" in stage["inputs"]) is (not is_bridge)
                assert stage["dispatch_correlation_input"] == "yoke_dispatch_id"

        assert by_id["platform-production"]["status"] == "disabled"
        assert by_id["yoke-hosted-production"]["status"] == "disabled"

    def test_yoke_immediate_flows_skip_ci_without_rewriting_history(self):
        by_id = {flow["id"]: flow for flow in _SEED_FLOWS}
        assert by_id["yoke-hosted-stage"]["status"] == "disabled"
        assert by_id["yoke-hosted-production-hotfix"]["status"] == "disabled"
        for flow_id in (
            "yoke-hosted-stage-no-ci-gate",
            "yoke-hosted-production-hotfix-no-ci-gate",
        ):
            flow = by_id[flow_id]
            assert flow["status"] == "active"
            workflow_stages = [
                stage for stage in json.loads(flow["stages"])
                if stage.get("executor") == "github-actions-workflow"
            ]
            assert workflow_stages
            assert all(stage["wait_for_ci"] is False for stage in workflow_stages)

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

    def test_buzz_delivery_flows_end_with_smoke_evidence(self):
        by_id = {flow["id"]: flow for flow in _SEED_FLOWS}
        expected = {
            "buzz-production-release": [
                "migration_apply", "merged", "prod-deploy", "smoke", "complete",
            ],
            "buzz-production-hotfix": [
                "migration_apply", "merged", "production-deploy", "smoke", "complete",
            ],
        }
        for flow_id, expected_stages in expected.items():
            stages = json.loads(by_id[flow_id]["stages"])
            assert [
                stage.get("name", stage.get("kind")) for stage in stages
            ] == expected_stages
            smoke = next(stage for stage in stages if stage.get("name") == "smoke")
            assert smoke["executor"] == "github-actions-workflow"
            assert smoke["workflow"] == "buzz-smoke.yml"


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
                conn.execute(
                    "INSERT INTO projects (id, slug) VALUES (43, 'platform')"
                )
                conn.commit()
                flow_cmd_init(conn)
                rows = conn.execute(
                    "SELECT id, project_id, status "
                    "FROM deployment_flows ORDER BY id"
                ).fetchall()
                by_id = {
                    str(row[0]): (int(row[1]), str(row[2]))
                    for row in rows
                }
                assert set(by_id) == {f["id"] for f in _SEED_FLOWS}
                for flow in _SEED_FLOWS:
                    expected = {
                        "yoke": 41,
                        "buzz": 42,
                        "platform": 43,
                    }[flow["project"]]
                    assert by_id[str(flow["id"])][0] == expected
                assert by_id["yoke-hosted-production"][1] == "disabled"
                buzz_stages = json.loads(conn.execute(
                    "SELECT stages FROM deployment_flows "
                    "WHERE id = 'buzz-production-release'"
                ).fetchone()[0])
                assert all(
                    "dispatch_correlation_input" not in stage
                    for stage in buzz_stages
                )
            finally:
                conn.close()
