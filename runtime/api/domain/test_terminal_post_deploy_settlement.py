"""Terminal settlement consumes admitted production proof, never intake CI."""

from __future__ import annotations

from runtime.api.domain.terminal_post_deploy_settlement_test_support import (
    _accept_member_qa as _accept_member_qa,
    _source_member as _source_member,
)


import json

import pytest

from runtime.api.domain.run_success_member_settlement_test_support import _run, _status
from runtime.api.domain.status_transition_preflight_test_support import (
    _isolate_status_effects,
)
from runtime.api.fixtures.backlog import insert_qa_run
from runtime.api.fixtures.dispatch_actor import register_session_actor
from runtime.api.fixtures.runtime import DEFAULT_TEST_SESSION_ID
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_contract import deployment_qa_stage_subject
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)
from yoke_core.domain.qa_execution_environment_target import (
    target_digest,
    canonical_target,
)
from yoke_core.domain.deployment_run_collective_finalization import mark_settling
from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
from yoke_core.domain.qa_terminal_requirement_errors import _recovery_instruction
from yoke_core.domain.qa_terminal_settlement import terminal_transition_result
from yoke_core.domain.workflow_runtime import (
    load_item_workflow_runtime,
)


@pytest.mark.parametrize("workflow", ("dash", "blitz"))
@pytest.mark.parametrize("environment", ("stage", "prod"))
def test_production_source_closes_member_and_finalizes_run(
    test_db,
    monkeypatch,
    workflow,
    environment,
):
    # The source is the item's own case; a post-deploy plan is answered by
    # its release's plan group, never by a copy on the member.
    _isolate_status_effects(monkeypatch)
    register_session_actor(test_db, DEFAULT_TEST_SESSION_ID)
    item_id, run_id, source_id = _source_member(
        test_db,
        workflow=workflow,
        plan_source=False,
        environment=environment,
    )
    _accept_member_qa(test_db, run_id=run_id, item_id=item_id)
    assert _status(test_db, item_id) == "release"
    test_db.execute(
        "UPDATE deployment_runs SET status='executing' WHERE id=%s", (run_id,)
    )
    test_db.commit()
    mark_settling(test_db, run_id)
    runtime = load_item_workflow_runtime(test_db, item_id)
    assert terminal_transition_result(test_db, item_id, "done", runtime) is None
    refusal = cmd_update(run_id, "status", "succeeded")
    assert refusal is None, refusal
    assert _status(test_db, item_id) == "done"
    assert _run(test_db, run_id) == ("succeeded", True)
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM qa_runs WHERE qa_requirement_id=%s", (source_id,)
        ).fetchone()[0]
        == 0
    )
    assert (
        test_db.execute(
            "SELECT waived_at FROM qa_requirements WHERE id=%s", (source_id,)
        ).fetchone()[0]
        is None
    )


@pytest.mark.parametrize(
    "proof", ("missing", "failed", "unsettled", "wrong-commit", "wrong-environment")
)
def test_terminal_source_still_blocks_without_current_accepted_proof(test_db, proof):
    item_id, run_id, source_id = _source_member(
        test_db,
        workflow="blitz",
        plan_source=False,
    )
    if proof in {"wrong-commit", "wrong-environment"}:
        _accept_member_qa(test_db, run_id=run_id, item_id=item_id)
        target = deployment_qa_execution_target(
            test_db,
            deployment_qa_stage_subject(
                test_db, run_id=run_id, stage_name="member-qa", member_item_id=item_id
            ),
        )
        if proof == "wrong-commit":
            target["deployment"]["release_lineage"] = "d" * 40
            # Individual passes settle without a walk; the latest actual
            # attempt must also prove the wrong target for this refusal.
            for case in test_db.execute(
                "SELECT id,method_config FROM qa_requirements WHERE deployment_run_id=%s "
                "AND method_id IS NOT NULL", (run_id,)
            ).fetchall():
                from yoke_core.domain.qa_requirement_pass_currency import stamp_executed_method_config

                attempt = insert_qa_run(test_db, qa_requirement_id=case["id"],
                    verdict="pass", raw_result=stamp_executed_method_config(
                        "{}", case["method_config"], execution_target_digest=target_digest(target)))
                test_db.execute(
                    "INSERT INTO qa_artifacts(qa_run_id,artifact_type,artifact_handle,created_at) "
                    "VALUES (%s,'log','evidence://wrong-target',now())", (attempt["id"],))

        else:
            test_db.execute(
                "UPDATE qa_requirements SET target_env='stage' WHERE id=%s",
                (source_id,),
            )
        test_db.execute(
            "UPDATE qa_plan_executions SET execution_target_json=%s, "
            "execution_target_digest=%s WHERE deployment_run_id=%s",
            (canonical_target(target), target_digest(target), run_id),
        )
    elif proof != "missing":
        materialized = materialize_deployment_qa_stage(
            test_db,
            deployment_run_id=run_id,
            deployment_stage="member-qa",
            deployment_member_item_id=item_id,
        )
        insert_qa_run(
            test_db,
            qa_requirement_id=materialized["created_requirement_ids"][0],
            verdict="fail" if proof == "failed" else None,
        )
    # A green intake run must never replace missing admitted production proof.
    insert_qa_run(
        test_db,
        qa_requirement_id=source_id,
        verdict="pass",
        raw_result=json.dumps({"verification_tree": {"head_sha": "a" * 40}}),
    )
    test_db.execute(
        "UPDATE deployment_runs SET status='executing' WHERE id=%s", (run_id,)
    )
    test_db.commit()
    mark_settling(test_db, run_id)
    result = terminal_transition_result(
        test_db,
        item_id,
        "done",
        load_item_workflow_runtime(test_db, item_id),
    )
    assert result and result["error_code"] == "GATE_QA_TERMINAL_VERDICT"
    assert "post-deploy-unaccepted" in result["error"]
    assert "yoke watch qa-plan" in result["error"]
    assert "record-verdict" not in result["error"]
    assert _status(test_db, item_id) == "release"


@pytest.mark.parametrize("method", ("browser-inspection", "exploratory-mission"))
def test_flow_derived_non_ci_recovery_uses_the_case_runner(method):
    assert _recovery_instruction(
        {"id": 9, "method_id": method, "requirement_source": "flow_derived"}
    ) == ("Run `yoke qa case run --requirement-id 9`")
