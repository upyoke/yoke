"""Run/stage state coherence for ephemeral-deploy through the real pipeline.

Pure-unit like the sibling pipeline tests (every DB seam mocked), but the
executor dispatch layer is REAL: ``run_pipeline`` -> ``_dispatch_executor``
-> mocked ``exec_ephemeral_deploy``. Proves the new executor advances the
existing ``deployment_runs`` stage/status state coherently, emits the
stage events, halts the chain on failure, and receives the worktree-tier
branch (item-bound) or the stage-config branch (item-less).
"""

from __future__ import annotations

import json
from unittest import mock

from yoke_core.domain import (
    deploy_pipeline,
    deploy_pipeline_executors,
    deploy_pipeline_gates,
    deploy_pipeline_reporting,
    deploy_qa_recorder,
)

_RUN_ID = "run-eph-001"
_STAGES = json.dumps([
    {"name": "ephemeral-deploy", "executor": "ephemeral-deploy",
     "branch": "cfg-branch"},
    {"name": "complete", "executor": "auto"},
])


class _Harness:
    """Mocked-DB pipeline harness recording run mutations + events."""

    def __init__(self, member_items=()):
        self.member_items = list(member_items)
        self.db_calls = []
        self.events = []

    def yoke_db(self, *args, sd=None):
        self.db_calls.append(args)
        if args[:2] == ("runs", "get"):
            return f"{_RUN_ID}|yoke|flow-eph|ephemeral||created|"
        if args[:2] == ("runs", "items"):
            return "\n".join(
                f"{_RUN_ID}|{item}" for item in self.member_items
            )
        if args[:3] == ("items", "get", "YOK-42") and args[3] == "worktree":
            return "item-branch"
        if args[:3] == ("items", "get", "YOK-42") and args[3] == "status":
            return "implemented"
        return ""

    def flow_db(self, *args, sd=None):
        if args[0] == "stages":
            return _STAGES
        if args[0] == "get":
            return "ephemeral"
        return ""

    def emit(self, name, outcome, ctx, **kwargs):
        self.events.append((name, ctx.get("stage"), ctx.get("result")))

    def run(self, exec_rc):
        with mock.patch.object(
            deploy_pipeline, "_yoke_db", side_effect=self.yoke_db,
        ), mock.patch.object(
            deploy_pipeline_reporting, "_yoke_db",
            side_effect=self.yoke_db,
        ), mock.patch.object(
            deploy_pipeline_gates, "_yoke_db", side_effect=self.yoke_db,
        ), mock.patch.object(
            deploy_pipeline, "_flow_db", side_effect=self.flow_db,
        ), mock.patch.object(
            deploy_pipeline, "_project_db",
            side_effect=lambda *a, sd=None: "",
        ), mock.patch.object(
            deploy_pipeline, "checkout_for_project", return_value="/repo",
        ), mock.patch.object(
            deploy_pipeline, "_emit_run_event", side_effect=self.emit,
        ), mock.patch.object(
            deploy_qa_recorder, "cmd_seed_from_flow", return_value=0,
        ), mock.patch.object(
            deploy_qa_recorder, "cmd_record_stage_result", return_value=0,
        ), mock.patch.object(
            deploy_pipeline, "connect", return_value=mock.Mock(),
        ), mock.patch.object(
            deploy_pipeline, "query_scalar", return_value=0,
        ), mock.patch.object(
            deploy_pipeline_executors, "_item_label",
            side_effect=lambda first: f"YOK-{first}" if first else "",
        ), mock.patch(
            "yoke_core.domain.deploy_ephemeral.exec_ephemeral_deploy",
            return_value=exec_rc,
        ) as exec_deploy, mock.patch(
            "subprocess.run",
        ):
            rc = deploy_pipeline.run_pipeline(_RUN_ID, sd="/tmp/sd")
        return rc, exec_deploy

    def stage_updates(self):
        return [
            c[4] for c in self.db_calls
            if c[:4] == ("runs", "update", _RUN_ID, "current_stage")
        ]

    def status_updates(self):
        return [
            c[4] for c in self.db_calls
            if c[:4] == ("runs", "update", _RUN_ID, "status")
        ]


class TestEphemeralRunStatusItemless:
    def test_success_advances_run_state_with_config_branch(self):
        harness = _Harness()
        rc, exec_deploy = harness.run(exec_rc=0)

        assert rc == deploy_pipeline.EXIT_SUCCESS
        exec_deploy.assert_called_once_with(
            "yoke", branch="cfg-branch", repo_path="/repo",
            image_tag="", item_label="",
        )
        assert harness.stage_updates() == [
            "ephemeral-deploy", "complete", "complete",
        ]
        assert harness.status_updates() == ["executing", "succeeded"]
        assert (
            "DeploymentRunStageCompleted", "ephemeral-deploy", "success",
        ) in harness.events
        assert ("DeploymentRunSucceeded", None, None) in harness.events

    def test_failure_halts_chain_and_marks_run_failed(self):
        harness = _Harness()
        rc, _exec = harness.run(exec_rc=1)

        assert rc == deploy_pipeline.EXIT_STAGE_FAILED
        # Halt: the failed stage is marked, the chain never reaches
        # 'complete', and the run flips to failed.
        assert harness.stage_updates() == [
            "ephemeral-deploy", "ephemeral-deploy-failed",
        ]
        assert harness.status_updates() == ["executing", "failed"]
        assert (
            "DeploymentRunStageFailed", "ephemeral-deploy", "failed",
        ) in harness.events
        assert ("DeploymentRunFailed", "ephemeral-deploy", None) in (
            harness.events
        )
        assert not [
            e for e in harness.events if e[1] == "complete"
        ], "complete stage must not run after a failed deploy"


class TestEphemeralRunStatusItemBound:
    def test_worktree_branch_reaches_executor_without_merged_gate(
        self, capsys
    ):
        harness = _Harness(member_items=["42"])
        rc, exec_deploy = harness.run(exec_rc=0)

        assert rc == deploy_pipeline.EXIT_SUCCESS
        # The worktree tier resolves the item branch but never runs the
        # merged gate (resolve_flow_gate_branch returns "" for ephemeral).
        exec_deploy.assert_called_once_with(
            "yoke", branch="item-branch", repo_path="/repo",
            image_tag="", item_label="YOK-42",
        )
        assert "Ephemeral tier" in capsys.readouterr().out
        # Item deploy_stage dual-writes ride the same stage transitions.
        item_stage_updates = [
            c[4] for c in harness.db_calls
            if c[:4] == ("items", "update", "42", "deploy_stage")
        ]
        assert item_stage_updates == [
            "ephemeral-deploy", "complete", "complete",
        ]
        # Item-bound success also claims deployed_to for the target env.
        assert ("items", "update", "42", "deployed_to", "ephemeral") in [
            c[:5] for c in harness.db_calls
        ]
