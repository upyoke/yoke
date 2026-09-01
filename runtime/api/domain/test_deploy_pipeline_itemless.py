"""Item-less deployment run coverage for run_pipeline.

Environment-level deploys (stage bootstrap/proof deploys, operator
redeploys) carry zero member items by design.  Pure-unit like the
sibling test_deploy_pipeline_full.py: every DB/step_runner seam is mocked.
"""

from __future__ import annotations

import json
from unittest import mock

from yoke_core.domain import (
    deploy_pipeline,
    deploy_pipeline_gates,
    deploy_pipeline_run_context,
    deploy_pipeline_run_updates,
    deploy_qa_recorder,
)


class TestItemLessRun:
    """run_pipeline executes an item-less run to success.

    The run row's status/current_stage must advance while every
    item-bound step (branch verification, item reads/writes,
    deployed_to) is skipped.
    """

    def test_item_less_run_executes_to_success(self, capsys, monkeypatch):
        monkeypatch.setenv("YOKE_ENV", "prod")
        run_id = "run-env-001"
        stages = json.dumps([
            {"name": "merged", "step_runner": "auto"},
            {"name": "complete", "step_runner": "auto"},
        ])
        db_calls = []
        run_mutations = []

        def fake_yoke_db(*args, sd=None):
            db_calls.append(args)
            if args[:2] == ("runs", "get"):
                # id|project|flow|tier|environment|lineage|status|stage
                return (
                    f"{run_id}|yoke|flow-env|persistent|stage|"
                    f"{'d' * 40}|created|"
                )
            return ""

        def fake_flow_db(*args, sd=None):
            if args[0] == "stages":
                return stages
            if args[0] == "get":
                return "stage"
            return ""

        def fake_update_run_field(run_id, field, value):
            run_mutations.append((run_id, field, value))

        dispatched = []

        def fake_dispatch(stage, **kwargs):
            dispatched.append((
                stage["name"], kwargs["project_repo_path"],
                kwargs["product_repo_path"],
                kwargs["image_tag"],
                kwargs["release_lineage"],
            ))
            return 0, ""

        verify = mock.Mock()
        checkout_lookup = mock.Mock(return_value="/repo")
        with mock.patch.object(
            deploy_pipeline, "resolve_flow_gate_branch", return_value="stage",
        ), mock.patch.object(
            deploy_pipeline, "validate_itemless_product_source",
            return_value=mock.Mock(
                repo_path="/pinned/product",
                image_tag="abc123def456",
            ),
        ), mock.patch.object(
            deploy_pipeline, "_yoke_db", side_effect=fake_yoke_db,
        ), mock.patch.object(
            deploy_pipeline_run_updates,
            "update_run_field",
            side_effect=fake_update_run_field,
        ), mock.patch.object(
            deploy_pipeline, "_flow_db", side_effect=fake_flow_db,
        ), mock.patch.object(
            deploy_pipeline, "_project_db", return_value="",
        ), mock.patch.object(
            deploy_pipeline, "resolve_project_checkout_path", checkout_lookup,
        ), mock.patch.object(
            deploy_pipeline, "resolve_flow_target",
            return_value=("persistent", "stage"),
        ), mock.patch.object(
            deploy_pipeline_run_context, "_emit_run_event",
        ), mock.patch.object(
            deploy_pipeline_gates, "_verify_branch_merged", verify,
        ), mock.patch.object(
            deploy_pipeline, "_dispatch_step_runner", side_effect=fake_dispatch,
        ), mock.patch.object(
            deploy_pipeline, "_emit_run_event",
        ), mock.patch.object(
            deploy_qa_recorder, "cmd_seed_from_flow", return_value=0,
        ), mock.patch.object(
            deploy_qa_recorder, "cmd_record_stage_result", return_value=0,
        ), mock.patch.object(
            deploy_pipeline, "connect", return_value=mock.Mock(),
        ), mock.patch.object(
            deploy_pipeline, "query_scalar", return_value=0,
        ):
            rc = deploy_pipeline.run_pipeline(
                run_id, product_repo_path="/pinned/product",
                image_tag="abc123", sd="/tmp/sd",
            )

        assert rc == deploy_pipeline.EXIT_SUCCESS
        out = capsys.readouterr().out
        assert (
            f"Run {run_id} has no member items (environment-level deploy)"
            in out
        )
        assert (
            "Deployment authority: release_control_plane=prod "
            f"target=stage flow=flow-env run={run_id}"
        ) in out

        # Item-bound steps are skipped entirely: no branch verification,
        # no item reads or writes.
        verify.assert_not_called()
        assert not [c for c in db_calls if c and c[0] == "items"]

        # The run row still advances: both stages dispatch in order, the
        # run row's current_stage is written per stage plus the final
        # marker, and status moves executing -> succeeded.
        assert dispatched == [
            ("merged", "/repo", "/pinned/product", "abc123def456", "d" * 40),
            ("complete", "/repo", "/pinned/product", "abc123def456", "d" * 40),
        ]
        checkout_lookup.assert_called_once()
        stage_updates = [
            value for mutated_run, field, value in run_mutations
            if (mutated_run, field) == (run_id, "current_stage")
        ]
        assert stage_updates == ["merged", "complete", "complete"]
        status_updates = [
            value for mutated_run, field, value in run_mutations
            if (mutated_run, field) == (run_id, "status")
        ]
        assert status_updates == ["executing", "succeeded"]
        # deployed_to is item-bound — never claimed for an item-less run
        # even when the flow references a target environment.
        assert "Auto-set deployed_to" not in out


class TestResolveAndVerifyBranch:
    """Item-bound branch resolution stays intact for non-empty runs."""

    def test_item_less_skips_item_read_and_verification(self):
        with mock.patch.object(
            deploy_pipeline_gates, "_active_item_lane_branch",
        ) as lane_branch, mock.patch.object(
            deploy_pipeline_gates, "_verify_branch_merged",
        ) as verify:
            ok, first_item, branch = (
                deploy_pipeline_gates._resolve_and_verify_branch(
                    [], "/repo", target_branch="main", sd=None,
                )
            )
        assert (ok, first_item, branch) == (True, "", "")
        lane_branch.assert_not_called()
        verify.assert_not_called()

    def test_member_items_resolve_branch_and_verify(self, tmp_path):
        (tmp_path / ".git").mkdir()
        with mock.patch.object(
            deploy_pipeline_gates,
            "_active_item_lane_branch",
            return_value="feature-x",
        ), mock.patch.object(
            deploy_pipeline_gates, "_verify_branch_merged",
            return_value=(True, ""),
        ) as verify:
            ok, first_item, branch = (
                deploy_pipeline_gates._resolve_and_verify_branch(
                    ["42", "43"], str(tmp_path), target_branch="main", sd=None,
                )
            )
        assert (ok, first_item, branch) == (True, "42", "feature-x")
        verify.assert_called_once_with(
            "feature-x", "42", str(tmp_path), "main"
        )

    def test_failed_verification_propagates_not_ok(self, tmp_path, capsys):
        (tmp_path / ".git").mkdir()
        with mock.patch.object(
            deploy_pipeline_gates,
            "_active_item_lane_branch",
            return_value="feature-x",
        ), mock.patch.object(
            deploy_pipeline_gates, "_verify_branch_merged",
            return_value=(False, "Blocked: not on main"),
        ):
            ok, _first_item, _branch = (
                deploy_pipeline_gates._resolve_and_verify_branch(
                    ["42"], str(tmp_path), target_branch="main", sd=None,
                )
            )
        assert ok is False
        assert "Blocked: not on main" in capsys.readouterr().err
