"""Terminal settlement consumes admitted production proof, never intake CI."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.strategy_execution_test_support import seed_strategy_doc
from runtime.api.domain.test_dash_post_deploy_done_consumption import _bind_original
from runtime.api.domain.test_deployment_delivery_close_out_notice import _parked_owner
from runtime.api.domain.test_deployment_qa_admission_execution import (
    _seed_selected_requirement_run,
)
from runtime.api.domain.test_deployment_qa_stage_execution import _complete_case
from runtime.api.domain.test_no_obligation_member_close_out import _landing_evidence
from runtime.api.domain.test_run_success_member_settlement import _run, _status
from runtime.api.domain.test_status_transition_preflight import _isolate_status_effects
from runtime.api.fixtures.backlog import insert_item, insert_qa_run
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_contract import deployment_qa_stage_subject
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)
from yoke_core.domain.deployment_qa_stage_gate import _settle_stage_status
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_requirement_pass_currency import stamp_executed_method_config
from yoke_core.domain.qa_execution_environment_target import (
    target_digest,
    canonical_target,
)
from yoke_core.domain.deployment_run_collective_finalization import mark_settling
from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
from yoke_core.domain.item_merge_receipt_document import record_entry
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.qa_terminal_requirement_errors import _recovery_instruction
from yoke_core.domain.qa_terminal_settlement import terminal_transition_result
from yoke_core.domain.strategy_execution import link_execution_document
from yoke_core.domain.workflow_registry import publish_workflow_version
from yoke_core.domain.workflow_runtime import (
    load_item_workflow_runtime,
    load_workflow_runtime,
)


def _accept_member_qa(conn, *, run_id: str, item_id: int) -> None:
    # Prepare accepted evidence without the notice's independent early close;
    # the run-success command below must execute the whole settlement itself.
    materialize_deployment_qa_stage(
        conn,
        deployment_run_id=run_id,
        deployment_stage="member-qa",
        deployment_member_item_id=item_id,
    )
    execution = begin_plan_execution(
        conn,
        deployment_run_id=run_id,
        deployment_stage="member-qa",
        deployment_member_item_id=item_id,
        actor_id="2",
        session_id=f"qa-{run_id}",
    )
    copy_id = _complete_case(conn, execution)
    copy = conn.execute(
        "SELECT method_config,execution_target_digest FROM qa_requirements WHERE id=%s",
        (copy_id,),
    ).fetchone()
    proof = stamp_executed_method_config(
        None,
        copy["method_config"],
        execution_target_digest=copy["execution_target_digest"],
    )
    conn.execute(
        "UPDATE qa_runs SET raw_result=%s WHERE qa_requirement_id=%s", (proof, copy_id)
    )
    conn.commit()
    subject = deployment_qa_stage_subject(
        conn, run_id=run_id, stage_name="member-qa", member_item_id=item_id
    )
    accepted = _settle_stage_status(
        conn,
        subject=subject,
        target=deployment_qa_execution_target(conn, subject),
        run_id=run_id,
        stage_name="member-qa",
        member_item_id=item_id,
    )
    assert accepted["accepted"]


def _source_member(
    conn, *, workflow: str, plan_source: bool, environment="prod"
) -> tuple[int, str, int]:
    # Retained workflow pins can carry done QA even when today's Dash does not.
    version_id = conn.execute(
        "SELECT current_version_id FROM workflows WHERE id=%s", (workflow,)
    ).fetchone()[0]
    definition = load_workflow_runtime(
        conn, workflow_id=workflow, workflow_version_id=version_id
    ).definition
    done = next(stage for stage in definition["stages"] if stage["id"] == "done")
    if not any(gate["id"] == "qa_verification" for gate in done["gates"]):
        done["gates"].append({"id": "qa_verification"})
        publish_workflow_version(conn, workflow_id=workflow, definition=definition)
    item_id = 9901
    run_id = "run-terminal-production-proof"
    insert_item(conn, id=item_id, workflow_id=workflow, status="release")
    _parked_owner(conn, f"holder-{item_id}", item_id)
    if workflow == "dash":
        _landing_evidence(conn, item_id)
    record_entry(
        conn,
        item_id=item_id,
        branch="source-member",
        target="main",
        commit_sha="a" * 40,
        merge_sha="b" * 40,
    )
    if workflow == "blitz":
        slug = "PRODUCTION-ACCEPTANCE"
        seed_strategy_doc(
            conn,
            slug,
            "# Work\n\n## Completion\n"
            "- Completed: all work\n- Changed: settlement\n"
            "- Remaining: nothing\n- Verification identities: production proof\n"
            "- Parent reconciliation: reconciled\n",
        )
        link_execution_document(
            conn,
            item_id=item_id,
            project_id=1,
            slug=slug,
            actor_id=2,
            session_id=f"holder-{item_id}",
        )
    source_id = _bind_original(conn, item_id=item_id)
    conn.execute(
        "UPDATE qa_requirements SET target_env=%s, "
        "requirement_source='flow_derived' WHERE id=%s",
        (environment, source_id),
    )
    if plan_source:
        source = conn.execute(
            "SELECT * FROM qa_requirements WHERE id=%s", (source_id,)
        ).fetchone()
        plan = create_plan(
            conn,
            project="yoke",
            slug="production-source",
            name="Production source",
            infer_target_environment=False,
        )
        replace_plan_cases(
            conn,
            plan_id=int(plan["id"]),
            cases=[
                {
                    "case_key": "production-capture",
                    "position": 1,
                    "method_id": "browser-inspection",
                    "instructions": source["instructions"],
                    "expected_outcome": source["expected_outcome"],
                    "method_config": json.loads(source["method_config"]),
                }
            ],
        )
        conn.execute(
            "UPDATE qa_requirements SET plan_id=%s,plan_case_key=%s WHERE id=%s",
            (plan["id"], "production-capture", source_id),
        )
    conn.commit()
    _seed_selected_requirement_run(
        conn,
        run_id=run_id,
        item_id=item_id,
        requirement_id=source_id,
        environment=environment,
    )
    return item_id, run_id, source_id


@pytest.mark.parametrize("workflow", ("dash", "blitz"))
@pytest.mark.parametrize("plan_source", (False, True))
@pytest.mark.parametrize("environment", ("stage", "prod"))
def test_production_source_closes_member_and_finalizes_run(
    test_db,
    monkeypatch,
    workflow,
    plan_source,
    environment,
):
    _isolate_status_effects(monkeypatch)
    item_id, run_id, source_id = _source_member(
        test_db,
        workflow=workflow,
        plan_source=plan_source,
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
        plan_source=True,
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
