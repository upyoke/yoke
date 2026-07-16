"""Seed-owned deployment-flow stage convergence."""

from __future__ import annotations

import json

from yoke_core.domain.deployment_flow_seed_stage import ensure_seed_stage


class _Conn:
    def __init__(self, stages):
        self.stages = json.dumps(stages)
        self.updates = []

    def execute(self, sql, params=()):
        if sql.startswith("SELECT stages FROM deployment_flows"):
            return self
        if sql.startswith("UPDATE deployment_flows SET stages"):
            self.stages = params[0]
            self.updates.append(params)
            return self
        raise AssertionError(sql)

    def fetchone(self):
        return (self.stages,)


def test_existing_seed_stage_is_replaced_in_place():
    conn = _Conn([
        {"name": "merged", "executor": "auto"},
        {
            "name": "artifact-publish",
            "executor": "github-actions-workflow",
            "workflow": "artifact-publish.yml",
            "inputs": {"source_sha": "{head_sha}"},
            "reconcile_by_head_sha": True,
        },
        {"name": "complete", "executor": "auto"},
    ])
    seed_stage = {
        "name": "artifact-publish",
        "executor": "github-actions-workflow",
        "workflow": "artifact-publish.yml",
        "inputs": {"source_sha": "{head_sha}"},
        "reconcile_by_head_sha": False,
    }

    ensure_seed_stage(
        conn,
        seed_flows=[{
            "id": "example-release",
            "stages": json.dumps([
                {"name": "merged", "executor": "auto"},
                seed_stage,
                {"name": "complete", "executor": "auto"},
            ]),
        }],
        flow_id="example-release",
        stage_name="artifact-publish",
        before_stage="complete",
    )

    stages = json.loads(conn.stages)
    assert stages == [
        {"name": "merged", "executor": "auto"},
        seed_stage,
        {"name": "complete", "executor": "auto"},
    ]
    assert len(conn.updates) == 1
