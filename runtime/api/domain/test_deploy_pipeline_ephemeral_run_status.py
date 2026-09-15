"""Run/stage state coherence for ephemeral-deploy through the real pipeline.

Pure-unit like the sibling pipeline tests (every control-plane seam mocked), but the
step_runner dispatch layer is REAL: ``run_pipeline`` ->
``dispatch_step_runner_with_receipt``
-> mocked ``exec_ephemeral_deploy``. Proves the new step_runner advances the
existing ``deployment_runs`` stage/status state coherently, emits the
stage events, halts the chain on failure, and receives the worktree-tier
branch (item-bound) or the stage-config branch (item-less).
"""

from __future__ import annotations

from unittest import mock

from yoke_core.domain import (
    deploy_pipeline_run_context,
    deploy_pipeline,
    deploy_pipeline_run_updates,
)

_RUN_ID = "run-eph-001"
_STAGES = [
    {
        "name": "ephemeral-deploy",
        "step_runner": "ephemeral-deploy",
        "branch": "cfg-branch",
    },
    {"name": "complete", "step_runner": "auto"},
]


class _Harness:
    """Mocked control-plane harness recording run mutations and events."""

    def __init__(self, member_items=()):
        self.member_items = list(member_items)
        self.run_mutations = []
        self.events = []
        self.stamps = []
        self.releases = []

    def stamp_item_field(self, item_id, field, value):
        self.stamps.append((int(item_id), field, value))
        return {"verified": True, "item_id": int(item_id)}

    def transition_member_to_release(self, item_id, run_id):
        self.releases.append((int(item_id), run_id))

    def update_run_field(self, run_id, field, value):
        self.run_mutations.append((run_id, field, value))

    def emit(self, name, outcome, ctx, **kwargs):
        self.events.append((name, ctx.get("stage"), ctx.get("result")))

    def run(self, exec_rc):
        members = [
            {
                "item_id": int(item),
                "public_ref": f"YOK-{item}",
                "status": "implemented",
                "branch": "item-branch",
            }
            for item in self.member_items
        ]
        context = {
            "run": {
                "id": _RUN_ID,
                "project": "yoke",
                "flow": "flow-eph",
                "target_tier": "ephemeral",
                "target_environment": "",
                "release_lineage": "",
                "status": "created",
                "current_stage": "",
            },
            "members": members,
            "stages": _STAGES,
        }
        with (
            mock.patch.object(
                deploy_pipeline.control_plane,
                "execution_context",
                return_value=context,
            ),
            mock.patch.object(
                deploy_pipeline_run_updates,
                "update_run_field",
                side_effect=self.update_run_field,
            ),
            mock.patch.object(
                deploy_pipeline.control_plane,
                "project_field",
                return_value="",
            ),
            mock.patch.object(
                deploy_pipeline.control_plane,
                "seed_qa",
                return_value=0,
            ),
            mock.patch.object(
                deploy_pipeline.control_plane,
                "record_qa_stage",
                return_value=None,
            ),
            mock.patch.object(
                deploy_pipeline.control_plane,
                "unresolved_qa",
                return_value=[],
            ),
            mock.patch.object(
                deploy_pipeline,
                "resolve_project_checkout_path",
                return_value="/repo",
            ),
            mock.patch.object(
                deploy_pipeline,
                "_emit_run_event",
                side_effect=self.emit,
            ),
            mock.patch.object(
                deploy_pipeline_run_context,
                "_emit_run_event",
                side_effect=self.emit,
            ),
            mock.patch(
                "yoke_core.domain.deploy_ephemeral.exec_ephemeral_deploy",
                return_value=exec_rc,
            ) as exec_deploy,
            mock.patch(
                "yoke_core.domain.deployment_item_stamp.stamp_item_field",
                side_effect=self.stamp_item_field,
            ),
            mock.patch.object(
                deploy_pipeline,
                "transition_member_to_release",
                side_effect=self.transition_member_to_release,
            ),
            mock.patch(
                "yoke_core.domain.deploy_pipeline_failure._report_failure_trace",
            ),
        ):
            rc = deploy_pipeline.run_pipeline(_RUN_ID, sd="/tmp/sd")
        return rc, exec_deploy

    def stage_updates(self):
        return [
            value
            for run_id, field, value in self.run_mutations
            if (run_id, field) == (_RUN_ID, "current_stage")
        ]

    def status_updates(self):
        return [
            value
            for run_id, field, value in self.run_mutations
            if (run_id, field) == (_RUN_ID, "status")
        ]


class TestEphemeralRunStatusItemless:
    def test_success_advances_run_state_with_config_branch(self):
        harness = _Harness()
        rc, exec_deploy = harness.run(exec_rc=0)

        assert rc == deploy_pipeline.EXIT_SUCCESS
        exec_deploy.assert_called_once_with(
            "yoke",
            branch="cfg-branch",
            repo_path="/repo",
            image_tag="",
            item_label="",
        )
        assert harness.stage_updates() == [
            "ephemeral-deploy",
            "complete",
            "complete",
        ]
        assert harness.status_updates() == ["executing", "succeeded"]
        assert (
            "DeploymentRunStageCompleted",
            "ephemeral-deploy",
            "success",
        ) in harness.events
        assert ("DeploymentRunSucceeded", None, None) in harness.events

    def test_failure_halts_chain_and_marks_run_failed(self):
        harness = _Harness()
        rc, _exec = harness.run(exec_rc=1)

        assert rc == deploy_pipeline.EXIT_STAGE_FAILED
        # Halt: the failed stage is marked, the chain never reaches
        # 'complete', and the run flips to failed.
        assert harness.stage_updates() == [
            "ephemeral-deploy",
            "ephemeral-deploy-failed",
        ]
        assert harness.status_updates() == ["executing", "failed"]
        assert (
            "DeploymentRunStageFailed",
            "ephemeral-deploy",
            "failed",
        ) in harness.events
        assert ("DeploymentRunFailed", "ephemeral-deploy", None) in (harness.events)
        assert not [e for e in harness.events if e[1] == "complete"], (
            "complete stage must not run after a failed deploy"
        )


class TestEphemeralRunStatusItemBound:
    def test_worktree_branch_reaches_step_runner_without_merged_gate(self, capsys):
        harness = _Harness(member_items=["42"])
        rc, exec_deploy = harness.run(exec_rc=0)

        assert rc == deploy_pipeline.EXIT_SUCCESS
        # The worktree tier resolves the item branch but never runs the
        # merged gate (resolve_flow_gate_branch returns "" for ephemeral).
        exec_deploy.assert_called_once_with(
            "yoke",
            branch="item-branch",
            repo_path="/repo",
            image_tag="",
            item_label="YOK-42",
        )
        assert "Ephemeral tier" in capsys.readouterr().out
        assert harness.releases == [(42, _RUN_ID)]
        assert [row for row in harness.stamps if row[1] == "deploy_stage"] == [
            (42, "deploy_stage", "ephemeral-deploy"),
            (42, "deploy_stage", "complete"),
            (42, "deploy_stage", "complete"),
        ]
        assert (42, "deployed_to", "ephemeral") in harness.stamps
