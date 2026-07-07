"""Kind-typed ``migration_apply`` stage coverage for run_pipeline.

Exercises the prod-flow stage shape ``{"kind": "migration_apply", ...}``
through the REAL ``run_pipeline`` → ``_dispatch_executor`` →
``_dispatch_migration_apply`` layers.  The governed runner is mocked at
exactly its boundary — ``check_implementing_to_reviewing_implementation_gate``
(the evidence gate over the rehearse → lease → backup → live-apply
contract); the governed apply itself never runs inside the pipeline.
Pure-unit like the sibling test_deploy_pipeline_itemless.py: every
DB/executor seam is mocked.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest import mock

from yoke_core.domain import (
    deploy_pipeline,
    deploy_pipeline_executors,
    deploy_pipeline_migration,
    deploy_pipeline_reporting,
    deploy_qa_recorder,
)
from yoke_core.domain.db_mutation_gate_shared import GateOutcome


# Mirrors the yoke-prod-release seed shape: the kind stage carries no
# "name"/"executor" keys on the flow row.
PROD_STAGES = json.dumps([
    {"kind": "migration_apply", "model_name": "primary",
     "lifecycle_phase": "implementing"},
    {"name": "merged", "executor": "auto"},
    {"name": "complete", "executor": "auto"},
])


def _execute(
    *,
    member_items=(),
    gate=None,
    from_stage="",
    current_stage="",
    run_status="created",
    stages=PROD_STAGES,
):
    """Run the real pipeline with every DB seam mocked; return observables."""
    run_id = "run-mig-001"
    db_calls = []

    def fake_yoke_db(*args, sd=None):
        db_calls.append(args)
        if args[:2] == ("runs", "get"):
            # id|project|flow|target_env|lineage|status|current_stage
            return (
                f"{run_id}|yoke|yoke-prod-release|prod|"
                f"|{run_status}|{current_stage}"
            )
        if args[:2] == ("runs", "items"):
            return "\n".join(f"{run_id}|{i}" for i in member_items)
        return ""

    def fake_flow_db(*args, sd=None):
        if args[0] == "stages":
            return stages
        if args[0] == "get":
            return "prod"
        return ""

    if gate is None:
        gate = mock.Mock(return_value=GateOutcome(passed=True))
    pipeline_events = []
    stage_events = []
    qa_results = []

    def record_pipeline_event(name, outcome, ctx, **kwargs):
        pipeline_events.append((name, dict(ctx)))

    def record_stage_event(name, outcome, ctx, **kwargs):
        stage_events.append((name, dict(ctx)))

    def record_qa(_run_id, stage_name, verdict, script_dir=None):
        qa_results.append((stage_name, verdict))
        return 0

    first_item = str(member_items[0]) if member_items else ""
    branch = "feature-x" if member_items else ""

    with mock.patch.object(
        deploy_pipeline, "resolve_flow_gate_branch", return_value="main",
    ), mock.patch.object(
        deploy_pipeline, "_resolve_and_verify_branch",
        return_value=(True, first_item, branch),
    ), mock.patch.object(
        deploy_pipeline, "_yoke_db", side_effect=fake_yoke_db,
    ), mock.patch.object(
        deploy_pipeline_reporting, "_yoke_db", side_effect=fake_yoke_db,
    ), mock.patch.object(
        deploy_pipeline, "_flow_db", side_effect=fake_flow_db,
    ), mock.patch.object(
        deploy_pipeline, "_project_db", return_value="",
    ), mock.patch.object(
        deploy_pipeline, "checkout_for_project", return_value="/repo",
    ), mock.patch.object(
        deploy_pipeline, "_emit_run_event", side_effect=record_pipeline_event,
    ), mock.patch.object(
        deploy_pipeline_migration, "_emit_run_event",
        side_effect=record_stage_event,
    ), mock.patch.object(
        deploy_pipeline_migration,
        "check_implementing_to_reviewing_implementation_gate", gate,
    ), mock.patch.object(
        deploy_qa_recorder, "cmd_seed_from_flow", return_value=0,
    ), mock.patch.object(
        deploy_qa_recorder, "cmd_record_stage_result", side_effect=record_qa,
    ), mock.patch.object(
        deploy_pipeline, "connect", return_value=mock.Mock(),
    ), mock.patch.object(
        deploy_pipeline, "query_scalar", return_value=0,
    ), mock.patch.object(
        deploy_pipeline, "_converge_seeded_flow_config",
    ):
        rc = deploy_pipeline.run_pipeline(
            run_id, from_stage=from_stage, sd="/tmp/sd",
        )

    return SimpleNamespace(
        rc=rc, run_id=run_id, db_calls=db_calls, gate=gate,
        pipeline_events=pipeline_events, stage_events=stage_events,
        qa_results=qa_results,
    )


def _stage_updates(result):
    return [
        c[4] for c in result.db_calls
        if c[:4] == ("runs", "update", result.run_id, "current_stage")
    ]


def _status_updates(result):
    return [
        c[4] for c in result.db_calls
        if c[:4] == ("runs", "update", result.run_id, "status")
    ]


def _stage_completed_events(result):
    return [
        ctx for name, ctx in result.stage_events
        if name == "DeploymentRunStageCompleted"
    ]


class TestKindStageParsing:
    """_parse_stages derives stable addressing for kind-typed stages."""

    def test_parse_stages_derives_kind_stage_keys(self):
        parsed = deploy_pipeline._parse_stages(PROD_STAGES)
        assert parsed[0]["name"] == "migration-apply"
        assert parsed[0]["executor"] == "migration_apply"
        assert parsed[0]["kind"] == "migration_apply"
        assert parsed[0]["config"]["model_name"] == "primary"
        # Executor-shaped stages keep explicit keys; kind stays empty.
        assert parsed[1]["name"] == "merged"
        assert parsed[1]["executor"] == "auto"
        assert parsed[1]["kind"] == ""

    def test_operator_name_override_wins(self):
        stages = json.dumps([
            {"kind": "migration_apply", "model_name": "primary",
             "lifecycle_phase": "implementing", "name": "db-migrate"},
        ])
        parsed = deploy_pipeline._parse_stages(stages)
        assert parsed[0]["name"] == "db-migrate"
        assert parsed[0]["kind"] == "migration_apply"


class TestItemLessKindStage:
    """Item-less run (the normal prod-release case) passes cleanly."""

    def test_no_pending_migrations_passes_with_note(self, capsys):
        result = _execute(member_items=())
        assert result.rc == deploy_pipeline.EXIT_SUCCESS
        # No member items -> no db_mutation_profile anywhere -> the
        # governed boundary is never consulted (same "nothing to apply"
        # rule the lifecycle gate applies to state=none profiles).
        result.gate.assert_not_called()
        # The stage advances run state under the derived name.
        assert _stage_updates(result) == [
            "migration-apply", "merged", "complete", "complete",
        ]
        assert _status_updates(result) == ["executing", "succeeded"]
        # Explicit stage-result note rides the pre-emitted completion event.
        completed = _stage_completed_events(result)
        assert len(completed) == 1
        ctx = completed[0]
        assert ctx["stage"] == "migration-apply"
        assert ctx["result"] == "success"
        assert ctx["model_name"] == "primary"
        assert ctx["lifecycle_phase"] == "implementing"
        assert ctx["items_verified"] == 0
        assert "nothing to apply at deploy time" in ctx["note"]
        assert "nothing to apply at deploy time" in capsys.readouterr().out
        # QA records a pass for the derived stage name.
        assert ("migration-apply", "pass") in result.qa_results


class TestItemBoundKindStage:
    """Item-bound runs route through the governed evidence gate."""

    def test_declared_claim_routes_through_governed_gate(self):
        gate = mock.Mock(return_value=GateOutcome(passed=True))
        result = _execute(member_items=("42",), gate=gate)
        assert result.rc == deploy_pipeline.EXIT_SUCCESS
        gate.assert_called_once_with(42)
        assert _stage_updates(result) == [
            "migration-apply", "merged", "complete", "complete",
        ]
        completed = _stage_completed_events(result)
        assert len(completed) == 1
        assert completed[0]["items_verified"] == 1
        assert "evidence verified" in completed[0]["note"]

    def test_gate_failure_marks_stage_failed_and_halts(self, capsys):
        gate = mock.Mock(return_value=GateOutcome(
            passed=False,
            errors=[
                "module 'mod_x': no migration_audit row with "
                "state='completed' found on the authoritative DB",
            ],
        ))
        result = _execute(member_items=("42",), gate=gate)
        assert result.rc == deploy_pipeline.EXIT_STAGE_FAILED
        # Failure marker carries the derived stage name; the run halts
        # before merged ever dispatches.
        assert _stage_updates(result) == [
            "migration-apply", "migration-apply-failed",
        ]
        assert _status_updates(result) == ["executing", "failed"]
        assert result.qa_results == [("migration-apply", "fail")]
        failed = [
            ctx for name, ctx in result.pipeline_events
            if name == "DeploymentRunStageFailed"
        ]
        assert len(failed) == 1
        assert failed[0]["stage"] == "migration-apply"
        assert "YOK-42" in failed[0]["executor_diagnostic"]
        assert "mod_x" in failed[0]["executor_diagnostic"]
        assert [
            name for name, _ in result.pipeline_events
            if name == "DeploymentRunFailed"
        ]
        assert "YOK-42" in capsys.readouterr().err


class TestKindStageResume:
    """--from-stage and failed-marker resume address the derived name."""

    def test_from_stage_merged_skips_kind_stage(self):
        gate = mock.Mock(return_value=GateOutcome(passed=False, errors=["x"]))
        result = _execute(
            member_items=("42",), gate=gate, from_stage="merged",
        )
        assert result.rc == deploy_pipeline.EXIT_SUCCESS
        gate.assert_not_called()
        assert _stage_updates(result) == ["merged", "complete", "complete"]
        assert _stage_completed_events(result) == []

    def test_from_stage_targets_kind_stage_by_derived_name(self):
        gate = mock.Mock(return_value=GateOutcome(passed=True))
        result = _execute(
            member_items=("42",), gate=gate, from_stage="migration-apply",
        )
        assert result.rc == deploy_pipeline.EXIT_SUCCESS
        gate.assert_called_once_with(42)
        assert _stage_updates(result) == [
            "migration-apply", "merged", "complete", "complete",
        ]

    def test_failed_marker_auto_resumes_at_kind_stage(self):
        gate = mock.Mock(return_value=GateOutcome(passed=True))
        result = _execute(
            member_items=("42",), gate=gate,
            run_status="failed", current_stage="migration-apply-failed",
        )
        assert result.rc == deploy_pipeline.EXIT_SUCCESS
        gate.assert_called_once_with(42)
        assert _stage_updates(result) == [
            "migration-apply", "merged", "complete", "complete",
        ]


class TestDispatchGuards:
    """Defensive dispatch errors for malformed kind stages."""

    def test_unknown_kind_fails_with_named_error(self, capsys):
        rc, diag = deploy_pipeline_executors._dispatch_executor(
            {"name": "x", "executor": "", "kind": "weird_kind", "config": {}},
            run_id="run-1", member_items=[], github_repo="",
            project="yoke", project_repo_path="", branch="",
            first_item="", timeout_min=30, fresh=False, target_env="",
            gate_branch="main", sd="/tmp/sd",
        )
        assert (rc, diag) == (1, "")
        assert "unknown stage kind 'weird_kind'" in capsys.readouterr().err

    def test_unsupported_lifecycle_phase_fails_stage(self, capsys):
        stage = {
            "name": "migration-apply", "executor": "migration_apply",
            "kind": "migration_apply",
            "config": {"kind": "migration_apply", "model_name": "primary",
                       "lifecycle_phase": "release"},
        }
        rc, diag = deploy_pipeline_migration._dispatch_migration_apply(
            stage, run_id="run-1", member_items=[], project="yoke",
        )
        assert rc == 1
        assert "not wired for pipeline dispatch" in diag
        assert "not wired for pipeline dispatch" in capsys.readouterr().err

    def test_missing_model_name_fails_stage(self, capsys):
        stage = {
            "name": "migration-apply", "executor": "migration_apply",
            "kind": "migration_apply",
            "config": {"kind": "migration_apply",
                       "lifecycle_phase": "implementing"},
        }
        rc, diag = deploy_pipeline_migration._dispatch_migration_apply(
            stage, run_id="run-1", member_items=[], project="yoke",
        )
        assert rc == 1
        assert "model_name" in diag
        assert "model_name" in capsys.readouterr().err
