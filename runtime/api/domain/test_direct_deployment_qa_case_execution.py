"""Direct run/stage/member QA cases bind the frozen destination and execute.

A hand-authored member case used to land without execution_target_* so
``yoke qa case run`` told the holder to rematerialize a plan. Membership
changes on an executing run stay refused. Recovery is the case-run surface
the member holder already has.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.test_deployment_qa_stage_execution import _seed_run
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement
from yoke_core.domain.deployment_runs_crud_mutate import cmd_add_item
from yoke_core.domain.handlers import qa_requirement_create
from yoke_core.domain.qa_case_execution_context import get_case_execution_context
from yoke_core.domain.qa_requirement_config_update import apply_requirement_update
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef


COMMAND_CASE = {
    "method_id": "command",
    "qa_phase": "post_deploy",
    "instructions": "run the member smoke command",
    "expected_outcome": "the command passes",
    "method_config": {"command": "true"},
}


def _qa_stages() -> list[dict]:
    return [
        {
            "name": "deploy",
            "step_runner": "auto",
            "stage_kind": "execution",
            "scope": "run",
        },
        {
            "name": "item-qa",
            "step_runner": "qa",
            "stage_kind": "qa",
            "scope": "item",
            "target": {
                "kind": "persistent_environment",
                "environment": "stage",
                "source_stage": "deploy",
            },
            "verdict": {"mode": "agent_only"},
        },
    ]


def _add(run_id: str, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="qa.requirement.add",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="deployment_run", deployment_run_id=run_id),
        payload=payload,
    )


def test_create_binds_frozen_stage_target(test_db) -> None:
    _seed_run(
        test_db,
        run_id="run-direct-bind",
        stages=_qa_stages(),
        members=(9810,),
    )
    outcome = qa_requirement_create.handle_qa_requirement_add(
        _add(
            "run-direct-bind",
            {
                **COMMAND_CASE,
                "deployment_stage": "item-qa",
                "deployment_member_item": "YOK-9810",
            },
        )
    )
    assert outcome.primary_success, outcome.error
    row = test_db.execute(
        "SELECT execution_target_json, execution_target_digest, "
        "deployment_member_item_id FROM qa_requirements WHERE id=%s",
        (outcome.result_payload["requirement_id"],),
    ).fetchone()
    target = json.loads(row["execution_target_json"])
    assert int(row["deployment_member_item_id"]) == 9810
    assert target["environment"]["name"] == "stage"
    assert target["deployment"]["run_id"] == "run-direct-bind"
    assert target["deployment"]["member_item_id"] == 9810
    assert row["execution_target_digest"]


def test_unbound_existing_member_case_recovers_on_case_run(test_db) -> None:
    _seed_run(
        test_db,
        run_id="run-direct-recover",
        stages=_qa_stages(),
        members=(9811,),
    )
    row = insert_qa_requirement(
        test_db,
        item_id=None,
        deployment_run_id="run-direct-recover",
        deployment_stage="item-qa",
        deployment_member_item_id=9811,
        qa_kind="method_case",
        qa_phase="post_deploy",
        method_id="command",
        method_name="Command",
        runner_id="worktree_run",
        verdict_path="automatic",
        capability_requirements="[]",
        instructions="run the member smoke command",
        expected_outcome="the command passes",
        method_config=json.dumps({"command": "true"}),
        target_env="prod",
    )
    context = get_case_execution_context(test_db, requirement_id=int(row["id"]))
    assert context["execution_target"]["deployment"]["run_id"] == "run-direct-recover"
    assert context["execution_target"]["deployment"]["member_item_id"] == 9811
    # The contract carries the member as a ref, so the case's own command can
    # name its subject instead of hardcoding a run that already happened.
    assert context["deployment_member_ref"] == "YOK-9811"
    stored = test_db.execute(
        "SELECT execution_target_digest FROM qa_requirements WHERE id=%s",
        (int(row["id"]),),
    ).fetchone()
    assert stored["execution_target_digest"]


def test_flow_without_cases_materializes_direct_member_case(test_db) -> None:
    _seed_run(
        test_db,
        run_id="run-direct-empty-flow",
        stages=_qa_stages(),
        members=(9812,),
    )
    created = qa_requirement_create.handle_qa_requirement_add(
        _add(
            "run-direct-empty-flow",
            {
                **COMMAND_CASE,
                "deployment_stage": "item-qa",
                "deployment_member_item": "YOK-9812",
            },
        )
    )
    assert created.primary_success, created.error
    result = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id="run-direct-empty-flow",
        deployment_stage="item-qa",
        deployment_member_item_id=9812,
    )
    assert created.result_payload["requirement_id"] in result["existing_requirement_ids"]
    execution = begin_plan_execution(
        test_db,
        deployment_run_id="run-direct-empty-flow",
        deployment_stage="item-qa",
        deployment_member_item_id=9812,
        actor_id="2",
        session_id="direct-qa",
    )
    assert execution["roster"][0]["requirement_id"] == created.result_payload[
        "requirement_id"
    ]


def test_frozen_membership_stays_refused_while_existing_member_recovers(
    test_db,
) -> None:
    _seed_run(
        test_db,
        run_id="run-direct-frozen",
        stages=_qa_stages(),
        members=(9813,),
    )
    insert_item(test_db, id=9814, project_sequence=9814, title="Late", status="release")
    test_db.commit()
    with pytest.raises(ValueError, match="executing"):
        cmd_add_item("run-direct-frozen", 9814)
    row = insert_qa_requirement(
        test_db,
        item_id=None,
        deployment_run_id="run-direct-frozen",
        deployment_stage="item-qa",
        deployment_member_item_id=9813,
        qa_kind="method_case",
        qa_phase="post_deploy",
        method_id="command",
        method_name="Command",
        runner_id="worktree_run",
        verdict_path="automatic",
        capability_requirements="[]",
        instructions="run the member smoke command",
        expected_outcome="the command passes",
        method_config=json.dumps({"command": "true"}),
    )
    context = get_case_execution_context(test_db, requirement_id=int(row["id"]))
    assert context["execution_target"]["environment"]["name"] == "stage"


def test_named_prod_refuses_when_stage_declares_stage_before_receipt(
    test_db,
) -> None:
    _seed_run(
        test_db,
        run_id="run-direct-mismatch",
        stages=_qa_stages(),
        members=(9816,),
    )
    test_db.execute(
        "DELETE FROM deployment_stage_receipts WHERE run_id=%s",
        ("run-direct-mismatch",),
    )
    test_db.execute(
        "INSERT INTO environments(site,project_id,name,url,settings,created_at) "
        "SELECT id,1,'prod','https://prod.example.test',%s,%s FROM sites "
        "WHERE project_id=1 ORDER BY id LIMIT 1 "
        "ON CONFLICT(project_id,name) DO UPDATE SET url=EXCLUDED.url",
        (json.dumps({"hosts": {"app": "https://prod.example.test"}}),
         "2026-09-16T00:00:00Z"),
    )
    test_db.commit()
    outcome = qa_requirement_create.handle_qa_requirement_add(
        _add(
            "run-direct-mismatch",
            {
                **COMMAND_CASE,
                "deployment_stage": "item-qa",
                "deployment_member_item": "YOK-9816",
                "target_env": "prod",
            },
        )
    )
    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"
    assert "targets 'stage'" in outcome.error.message


def test_unbound_run_attached_case_refuses_at_composition_freeze(
    test_db, monkeypatch
) -> None:
    from runtime.api.domain.test_deployment_run_composition_freeze import (
        _environment,
        _flow,
        _known_carried,
        _run,
    )
    import yoke_core.domain.deployment_run_composition_freeze as composition

    _environment(test_db)
    _flow(test_db, "advanced-unbound-direct", advanced=True)
    insert_item(
        test_db,
        id=9820,
        project_sequence=9820,
        workflow_id="issue",
        status="release",
        deployment_flow="advanced-unbound-direct",
    )
    test_db.commit()
    monkeypatch.setattr(
        composition, "record_carried_work", lambda _conn, _run: _known_carried(9820)
    )
    _run(test_db, "run-unbound-direct", "advanced-unbound-direct", lineage="c" * 40)
    cmd_add_item("run-unbound-direct", 9820)
    row = insert_qa_requirement(
        test_db,
        item_id=None,
        deployment_run_id="run-unbound-direct",
        qa_kind="method_case",
        qa_phase="post_deploy",
        method_id="command",
        method_name="Command",
        runner_id="worktree_run",
        verdict_path="automatic",
        capability_requirements="[]",
        instructions="bind before start",
        expected_outcome="the command passes",
        method_config=json.dumps({"command": "true"}),
    )
    test_db.commit()
    with pytest.raises(ValueError, match=rf"requirement {int(row['id'])}.*before this run starts"):
        composition.freeze_run_composition(test_db, "run-unbound-direct")
    updated = apply_requirement_update(
        test_db, int(row["id"]), "target_env", "stage"
    )
    assert updated.ok
    digest = test_db.execute(
        "SELECT execution_target_digest FROM qa_requirements WHERE id=%s",
        (int(row["id"]),),
    ).fetchone()[0]
    assert digest
    composition.freeze_run_composition(test_db, "run-unbound-direct")
    frozen = apply_requirement_update(test_db, int(row["id"]), "target_env", "prod")
    assert not frozen.ok
    assert frozen.error_code == "frozen_requirement_immutable"
