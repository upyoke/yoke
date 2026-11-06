# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.strategy_execution_test_support import seed_strategy_doc

from runtime.api.domain.dash_post_deploy_done_consumption_test_support import (
    _bind_original,
)

from runtime.api.domain.deployment_delivery_close_out_notice_test_support import (
    _parked_owner,
)

from runtime.api.domain.deployment_qa_admission_execution_test_support import (
    _seed_selected_requirement_run,
)

from runtime.api.domain.deployment_qa_stage_execution_test_support import _complete_case

from runtime.api.domain.no_obligation_member_close_out_test_support import (
    _landing_evidence,
)

from runtime.api.domain.run_success_member_settlement_test_support import _run, _status

from runtime.api.domain.status_transition_preflight_test_support import (
    _isolate_status_effects,
)

from runtime.api.fixtures.backlog import insert_item, insert_qa_run

from runtime.api.fixtures.dispatch_actor import register_session_actor

from runtime.api.fixtures.runtime import DEFAULT_TEST_SESSION_ID

from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)

from yoke_core.domain.deployment_qa_stage_contract import deployment_qa_stage_subject

from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)

from yoke_core.domain.deployment_qa_stage_gate import _settle_stage_status

from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

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
    _complete_case(conn, execution)
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
