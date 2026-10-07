"""Each declared case environment survives materialization and delivery."""

import importlib
import json

import pytest

from runtime.api.domain.test_dash_post_deploy_done_consumption import _accept_member_qa
from runtime.api.domain.test_deployment_qa_admission_execution import (
    _seed_selected_requirement_run,
)
from runtime.api.domain.test_deployment_qa_stage_execution import _environment
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.deployment_item_completion_runs import latest_qa_member_run
from yoke_core.domain.deployment_qa_source_obligation import source_obligation_consumed
from yoke_core.domain.deployment_run_member_targeting import (
    run_needs_member,
    targeted_requirement_ids,
)
from yoke_core.domain.qa_deployment_member_attached_plans import (
    delivery_answered_plan_ids,
)
from yoke_core.domain.qa_gates import GateTarget, check_done_gate
from yoke_core.domain.qa_plan_attachments import (
    materialize_for_item,
    set_project_default,
)
from yoke_core.domain.qa_plan_detail import get_plan
from yoke_core.domain.qa_plan_edit import _current_cases
from yoke_core.domain.qa_plan_management import (
    QaPlanError,
    create_plan,
    replace_plan_cases,
)
from yoke_core.domain.qa_plan_rematerialize import rematerialize_for_item
from yoke_core.domain.qa_plan_case_currency import plan_case_divergence


CASE = {
    "case_key": "environment-proof",
    "method_id": "command",
    "instructions": "Run the command against the case target.",
    "expected_outcome": "The target answers successfully.",
    "method_config": {"command": "true"},
    "target_envs": ["stage", "prod"],
}
ITEM_ID = 28761


def _setup(conn, *, baselines=()):
    _environment(conn)
    conn.execute(
        "INSERT INTO environments(site,project_id,name,url,settings,created_at) "
        "SELECT id,1,'prod','https://prod.example.test','{}','2026-09-14T00:00:00Z' "
        "FROM sites WHERE project_id=1 ORDER BY id LIMIT 1 "
        "ON CONFLICT(project_id,name) DO NOTHING"
    )
    item = insert_item(
        conn,
        id=ITEM_ID,
        project_sequence=ITEM_ID,
        workflow_id="issue",
        status="release",
    )
    plan = create_plan(
        conn, project="yoke", slug="environment-obligations", target_environment="prod"
    )
    case = {**CASE, "host_baselines": list(baselines)}
    if baselines:
        case.update(
            method_id="machine-state-check",
            method_config={"assertions": [{"argv": ["/usr/bin/true"]}]},
        )
    replace_plan_cases(conn, plan_id=plan["id"], cases=[case])
    set_project_default(
        conn,
        plan_id=plan["id"],
        workflow_id="issue",
        transition_id="release",
        qa_phase="post_deploy",
    )
    return item, plan, case


def _requirements(conn):
    return {
        row["target_env"]: dict(row)
        for row in conn.execute(
            "SELECT id,target_env,execution_target_json,waived_at FROM qa_requirements "
            "WHERE item_id=%s AND deployment_run_id IS NULL",
            (ITEM_ID,),
        ).fetchall()
    }


def test_materialization_and_refresh_keep_both_environment_identities(test_db):
    item, plan, case = _setup(test_db)
    result = materialize_for_item(test_db, item_id=item["id"], transition_id="release")
    assert len(result["created_requirement_ids"]) == 2
    before = _requirements(test_db)
    assert set(before) == {"stage", "prod"}
    for name, row in before.items():
        assert json.loads(row["execution_target_json"])["environment"]["name"] == name
    again = materialize_for_item(test_db, item_id=item["id"], transition_id="release")
    assert again["created_requirement_ids"] == []
    assert set(again["existing_requirement_ids"]) == {
        row["id"] for row in before.values()
    }
    replace_plan_cases(
        test_db,
        plan_id=plan["id"],
        cases=[{**case, "instructions": "Run the amended command."}],
    )
    result = rematerialize_for_item(
        test_db, item_id=item["id"], transition_id="release"
    )
    assert result["waived_requirement_ids"] == []
    assert set(result["refreshed_requirement_ids"]) == {
        row["id"] for row in before.values()
    }
    assert all(
        plan_case_divergence(test_db, row["id"]) is None for row in before.values()
    )
    assert _current_cases(test_db, plan["id"])[0]["target_envs"] == ["stage", "prod"]
    detail = get_plan(test_db, plan_id=plan["id"])
    assert detail["cases"][0]["target_envs"] == ["stage", "prod"]
    assert {proof["target_env"] for proof in detail["cases"][0]["proofs"]} == {
        "stage",
        "prod",
    }


def test_targets_cross_product_with_host_baselines(test_db):
    baselines = ("fresh-host", "shell-preconfigured")
    item, _plan, _case = _setup(test_db, baselines=baselines)
    result = materialize_for_item(test_db, item_id=item["id"], transition_id="release")
    assert len(result["created_requirement_ids"]) == 4
    rows = test_db.execute(
        "SELECT target_env,host_baseline,starting_state FROM qa_requirements "
        "WHERE item_id=%s AND deployment_run_id IS NULL",
        (item["id"],),
    ).fetchall()
    assert {(row["target_env"], row["host_baseline"]) for row in rows} == {
        (environment, baseline)
        for environment in ("stage", "prod")
        for baseline in baselines
    }
    assert {row["starting_state"] for row in rows} == {"baseline"}


def test_refresh_waives_only_a_removed_environment(test_db):
    item, plan, case = _setup(test_db)
    materialize_for_item(test_db, item_id=item["id"], transition_id="release")
    before = _requirements(test_db)
    replace_plan_cases(
        test_db, plan_id=plan["id"], cases=[{**case, "target_envs": ["prod"]}]
    )
    result = rematerialize_for_item(
        test_db, item_id=item["id"], transition_id="release"
    )
    assert result["waived_requirement_ids"] == [before["stage"]["id"]]
    assert result["refreshed_requirement_ids"] == [before["prod"]["id"]]


def _run(conn, *, name, requirement_id, environment):
    _seed_selected_requirement_run(
        conn,
        run_id=name,
        item_id=ITEM_ID,
        requirement_id=requirement_id,
        environment=environment,
    )
    conn.execute(
        "UPDATE deployment_flows SET target_tier='persistent',target_environment_id=(SELECT id FROM environments WHERE project_id=1 AND name=%s),status='active' WHERE id=%s",
        (environment, f"flow-{name}"),
    )
    conn.commit()


def test_production_acceptance_cannot_close_an_unproven_stage_obligation(test_db):
    item, plan, _case = _setup(test_db)
    materialize_for_item(test_db, item_id=item["id"], transition_id="release")
    rows = _requirements(test_db)
    prod_run, stage_run = "run-environment-prod", "run-environment-stage"
    _run(test_db, name=prod_run, requirement_id=rows["prod"]["id"], environment="prod")
    _accept_member_qa(test_db, run_id=prod_run, item_id=ITEM_ID)
    assert source_obligation_consumed(
        test_db, item_id=ITEM_ID, source_requirement_id=rows["prod"]["id"]
    )
    assert not source_obligation_consumed(
        test_db, item_id=ITEM_ID, source_requirement_id=rows["stage"]["id"]
    )
    assert (
        delivery_answered_plan_ids(
            test_db, member_item_id=ITEM_ID, plan_ids=[plan["id"]]
        )
        == set()
    )
    gate = check_done_gate(GateTarget(item_id=ITEM_ID), str(test_db.info.dsn))
    assert not gate.passed
    assert "missing_target_proof" in "\n".join(gate.errors)
    assert "stage" in "\n".join(gate.errors)
    assert "configure an active delivery flow" in "\n".join(gate.errors)
    _run(
        test_db, name=stage_run, requirement_id=rows["stage"]["id"], environment="stage"
    )
    test_db.execute(
        "UPDATE items SET deployment_flow=%s WHERE id=%s", (f"flow-{prod_run}", ITEM_ID)
    )
    test_db.commit()
    assert run_needs_member(test_db, run_id=stage_run, item_id=ITEM_ID)
    assert targeted_requirement_ids(
        test_db, run_id=stage_run, item_id=ITEM_ID
    ) == frozenset({rows["stage"]["id"]})
    assert (
        latest_qa_member_run(test_db, item_id=ITEM_ID, target_env="stage")["id"]
        == stage_run
    )
    _accept_member_qa(test_db, run_id=stage_run, item_id=ITEM_ID)
    assert source_obligation_consumed(
        test_db, item_id=ITEM_ID, source_requirement_id=rows["stage"]["id"]
    )
    assert delivery_answered_plan_ids(
        test_db, member_item_id=ITEM_ID, plan_ids=[plan["id"]]
    ) == {plan["id"]}
    scoped = test_db.execute(
        "SELECT deployment_run_id,target_env FROM qa_requirements WHERE deployment_member_item_id=%s AND qa_kind='plan_case'",
        (ITEM_ID,),
    ).fetchall()
    assert {(row[0], row[1]) for row in scoped} == {
        (prod_run, "prod"),
        (stage_run, "stage"),
    }


@pytest.mark.parametrize(
    "targets", ["stage", ["stage", "stage"], [""], [False], ["missing"]]
)
def test_case_targets_refuse_invalid_or_unregistered_names(test_db, targets):
    _item, plan, case = _setup(test_db)
    with pytest.raises(QaPlanError, match="target_env"):
        replace_plan_cases(
            test_db, plan_id=plan["id"], cases=[{**case, "target_envs": targets}]
        )


def test_index_retirement_is_idempotent_and_preserves_rows(test_db):
    item, _plan, _case = _setup(test_db)
    test_db.execute(
        "CREATE UNIQUE INDEX idx_qa_requirement_materialization ON qa_requirements(item_id,plan_id,plan_case_key,COALESCE(host_baseline,''),workflow_transition_id) WHERE item_id IS NOT NULL AND plan_id IS NOT NULL"
    )
    migration = importlib.import_module(
        "yoke_core.domain.migrations.0058_qa_case_environment_materialization"
    )
    migration.apply(test_db)
    migration.apply(test_db)
    migration.invariants(test_db)
    result = materialize_for_item(test_db, item_id=item["id"], transition_id="release")
    assert len(result["created_requirement_ids"]) == 2


def test_single_target_execution_refuses_to_drop_a_declared_sibling():
    from yoke_core.domain.qa_plan_case_targets import require_single_execution_target

    with pytest.raises(QaPlanError, match="qa_plan_requires_environment_scopes"):
        require_single_execution_target([CASE], {"environment": {"name": "prod"}})
    require_single_execution_target(
        [{**CASE, "target_envs": ["prod"]}], {"environment": {"name": "prod"}}
    )


def test_empty_case_targets_keep_the_plan_default(test_db):
    item, plan, case = _setup(test_db)
    replace_plan_cases(test_db, plan_id=plan["id"], cases=[{**case, "target_envs": []}])
    result = materialize_for_item(test_db, item_id=item["id"], transition_id="release")
    assert len(result["created_requirement_ids"]) == 1
    (row,) = _requirements(test_db).values()
    assert row["target_env"] is None
    assert json.loads(row["execution_target_json"])["environment"]["name"] == "prod"
