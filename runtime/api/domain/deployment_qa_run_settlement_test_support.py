# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

from types import SimpleNamespace

from unittest.mock import patch

import pytest

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _complete_case,
    _plan,
    _seed_run,
    _stages,
)

from runtime.api.domain.deployment_qa_admission_execution_test_support import (
    _original_requirement,
)

from runtime.api.fixtures.backlog_inserts import insert_item, insert_qa_requirement

from runtime.api.fixtures.completed_delivery import seed_selected_requirement_run

from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.deployment_run_terminalization import terminalize_run_on

from yoke_core.domain.deployment_runs_crud_mutate import cmd_update

from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)

from yoke_core.domain.handlers.qa_run import handle_qa_run_record_verdict

from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

from yoke_core.domain.qa_terminal_settlement import find_unsettled_records


def exercise_late_verdict(test_db):
    item_id, run_id = 9752, "run-late-verdict"
    insert_item(
        test_db,
        id=item_id,
        project_sequence=item_id,
        workflow_id="issue",
        status="done",
    )
    original = _original_requirement(test_db, item_id=item_id, method_id=None)
    seed_selected_requirement_run(
        test_db, run_id=run_id, item_id=item_id, requirement_id=original
    )
    insert_qa_requirement(
        test_db,
        item_id=None,
        deployment_run_id=run_id,
        deployment_stage="member-qa",
        deployment_member_item_id=item_id,
        qa_phase="post_deploy",
        method_id="command",
        runner_id="worktree_run",
        verdict_path="automatic",
        method_config=json.dumps({"command": "true"}),
        target_env="stage",
        instructions="Run the member smoke command.",
        expected_outcome="The command passes.",
    )
    test_db.commit()
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="member-qa",
        deployment_member_item_id=item_id,
    )
    execution = begin_plan_execution(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="member-qa",
        deployment_member_item_id=item_id,
        actor_id="2",
        session_id="late-verdict",
    )
    _complete_case(test_db, execution)
    release_seeded_driver(test_db, run_id)
    test_db.commit()
    requirement_id = int(
        test_db.execute(
            "SELECT id FROM qa_requirements WHERE deployment_run_id=%s AND method_id IS NULL AND plan_id IS NULL",
            (run_id,),
        ).fetchone()[0]
    )
    # Acceptance is real; external run continuation is separately covered by
    # the auto-completion tests and must not invoke delivery from this fixture.
    with patch(
        "yoke_core.domain.deployment_run_auto_completion.continue_after_settlement",
        return_value=SimpleNamespace(completed=False, failure=""),
    ) as continue_run:
        outcome = handle_qa_run_record_verdict(
            FunctionCallRequest(
                function="qa.run.record_verdict",
                actor=ActorContext(actor_id="2", session_id="late-verdict"),
                target=TargetRef(
                    kind="qa_requirement", qa_requirement_id=requirement_id
                ),
                payload={
                    "performed_by": "agent",
                    "verdict": "pass",
                    "raw_result": json.dumps(
                        {
                            "verification_tree": {"head_sha": "c" * 40},
                            "note": "actual capture reviewed",
                        }
                    ),
                },
            )
        )
    continue_run.assert_called_once()
    assert outcome.primary_success, outcome.error
    raw = json.loads(
        test_db.execute(
            "SELECT raw_result FROM qa_runs WHERE id=%s",
            (outcome.result_payload["qa_run_id"],),
        ).fetchone()[0]
    )
    assert raw["execution_id"] == execution["id"]
    assert raw["evidence_artifact_ids"]
    assert raw["verification_tree"]["head_sha"] == "c" * 40
    assert raw["note"] == "actual capture reviewed"
    # Read durable acceptance without calling the gate: the verdict write itself settled it.
    assert (
        test_db.execute(
            "SELECT r.verdict FROM qa_runs r JOIN qa_requirements q ON q.id=r.qa_requirement_id "
            "WHERE q.deployment_run_id=%s AND q.qa_kind='deployment_stage_acceptance' ORDER BY r.id DESC LIMIT 1",
            (run_id,),
        ).fetchone()[0]
        == "pass"
    )
