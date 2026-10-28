"""Each declared case environment is proven by the release that reaches it.

A post-deploy plan is never copied onto an item. Each release runs it once as
a plan group at its item-scoped stage, with one row per case and required
host baseline whose declared environments include the release's environment.
"""

import importlib
import json

import pytest

from runtime.api.domain.test_deployment_qa_stage_execution import (
    _complete_case,
    _environment,
    _seed_run,
    _stages,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement
from runtime.api.fixtures.completed_delivery import pin_run_delivery
from yoke_core.domain.deployment_qa_plan_group_dispatch import settle_group
from yoke_core.domain.deployment_qa_plan_group_writes import (
    ensure_groups,
    group_subject,
)
from yoke_core.domain.deployment_qa_plan_groups import run_groups
from yoke_core.domain.qa_catalog_reads import list_plans
from yoke_core.domain.qa_gates import GateTarget, check_done_gate
from yoke_core.domain.qa_plan_attachments import (
    materialize_for_item,
    set_project_default,
)
from yoke_core.domain.qa_plan_detail import get_plan
from yoke_core.domain.qa_plan_edit import _current_cases
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_plan_management import (
    QaPlanError,
    create_plan,
    replace_plan_cases,
)
from yoke_core.domain.qa_plan_summary import plan_summary

CASE = {
    "case_key": "environment-proof",
    "method_id": "command",
    "instructions": "Run the command against the case target.",
    "expected_outcome": "The target answers successfully.",
    "method_config": {"command": "true"},
    "target_envs": ["stage", "prod"],
    "stage_reason": "creates_or_destroys_data",
}
ITEM_ID = 28761
SLUG = "environment-obligations"
RUNS = {"stage": "run-environment-stage", "prod": "run-environment-prod"}


def _production(case, targets):
    return {**case, "target_envs": targets, "stage_reason": None}


def _setup(conn, *, baselines=(), qa_phase="post_deploy"):
    _environment(conn)
    conn.execute(
        "INSERT INTO environments(site,project_id,name,url,settings,created_at) "
        "SELECT id,1,'prod','https://prod.example.test','{\"role\":{\"production\":true}}','2026-09-14T00:00:00Z' "
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
    plan = create_plan(conn, project="yoke", slug=SLUG, target_environment="prod")
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
        qa_phase=qa_phase,
    )
    return item, plan, case


def _release(conn, plan_id, environment):
    """A release of the item whose item-qa stage targets ``environment``."""
    conn.execute(
        "INSERT INTO qa_plan_item_attachments(item_id,plan_id,transition_id,qa_phase,attached_at) "
        "VALUES (%s,%s,'release','post_deploy','2026-10-28T00:00:00Z') "
        "ON CONFLICT DO NOTHING",
        (ITEM_ID, plan_id),
    )
    stages = _stages(plan_id)
    stages[1].pop("cases")
    stages[1]["target"]["environment"] = environment
    run_id = RUNS[environment]
    _seed_run(conn, run_id=run_id, stages=stages, members=(), existing_members=(ITEM_ID,))
    pin_run_delivery(conn, run_id, environment=environment)
    conn.execute(
        "UPDATE deployment_stage_receipts SET target_name=%s,observed_url=("
        "SELECT url FROM environments WHERE project_id=1 AND name=%s) "
        "WHERE run_id=%s AND stage_name='deploy'",
        (environment, environment, run_id),
    )
    created = ensure_groups(conn, run_id, "item-qa")
    conn.commit()
    return created


def _rows(conn, run_id=None):
    sql = (
        "SELECT id,item_id,deployment_member_item_id,plan_case_key,target_env,"
        "host_baseline,starting_state,execution_target_json FROM qa_requirements "
        "WHERE plan_id IS NOT NULL"
    )
    params: tuple = ()
    if run_id is not None:
        sql += " AND deployment_run_id=%s"
        params = (run_id,)
    return [dict(row) for row in conn.execute(sql + " ORDER BY id", params).fetchall()]


def _environment_of(row):
    return json.loads(row["execution_target_json"])["environment"]["name"]


def _pass_group(conn, run_id):
    execution = begin_plan_execution(
        conn,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=None,
        plan=SLUG,
        actor_id="2",
        session_id=f"{run_id}-qa",
    )
    _complete_case(conn, execution)
    group = run_groups(conn, [run_id], "item-qa")[-1]
    if not group.closed:
        settle_group(conn, group_subject(conn, run_id, "item-qa", group, require_active=False))
    assert run_groups(conn, [run_id], "item-qa")[-1].closed


def test_each_release_runs_the_case_at_its_own_declared_environment(test_db):
    _item, plan, _case = _setup(test_db)
    assert materialize_for_item(
        test_db, item_id=ITEM_ID, transition_id="release"
    )["created_requirement_ids"] == []
    for environment, run_id in RUNS.items():
        created = _release(test_db, plan["id"], environment)
        assert len(created) == 1
        (row,) = _rows(test_db, run_id)
        assert row["item_id"] is None and row["deployment_member_item_id"] is None
        assert row["target_env"] == environment
        assert _environment_of(row) == environment
        assert ensure_groups(test_db, run_id, "item-qa") == []
    assert _current_cases(test_db, plan["id"])[0]["target_envs"] == ["stage", "prod"]
    detail = get_plan(test_db, plan_id=plan["id"])
    assert detail["cases"][0]["target_envs"] == ["stage", "prod"]
    assert {proof["target_env"] for proof in detail["cases"][0]["proofs"]} == {
        "stage",
        "prod",
    }


def test_targets_cross_product_with_host_baselines(test_db):
    baselines = ("fresh-host", "shell-preconfigured")
    _item, plan, _case = _setup(test_db, baselines=baselines)
    for environment in RUNS:
        assert len(_release(test_db, plan["id"], environment)) == 2
    rows = _rows(test_db)
    assert {(row["target_env"], row["host_baseline"]) for row in rows} == {
        (environment, baseline)
        for environment in ("stage", "prod")
        for baseline in baselines
    }
    assert {row["starting_state"] for row in rows} == {"baseline"}


def test_inheriting_case_reads_every_environment_and_chain_baseline(test_db):
    baselines = ("fresh-host", "shell-preconfigured")
    _item, plan, case = _setup(test_db, baselines=baselines)
    replace_plan_cases(
        test_db,
        plan_id=plan["id"],
        cases=[
            case,
            {
                **case,
                "case_key": "follow",
                "position": 2,
                "host_baselines": [],
                "starting_state": "inherit",
            },
        ],
    )
    created = [
        *_release(test_db, plan["id"], "stage"),
        *_release(test_db, plan["id"], "prod"),
    ]
    assert len(created) == 8
    detail = get_plan(test_db, plan_id=plan["id"])
    follow = detail["cases"][1]
    assert {
        (proof["target_env"], proof["host_baseline"]) for proof in follow["proofs"]
    } == {
        (environment, baseline)
        for environment in ("stage", "prod")
        for baseline in baselines
    }
    assert len({proof["requirement_id"] for proof in follow["proofs"]}) == 4
    assert all(proof["requirement_id"] is not None for proof in follow["proofs"])
    assert "last_result" not in follow
    summary = plan_summary(detail, project="yoke")["cases"][1]
    assert summary["starting_state"] == "inherit"
    assert summary["starting_state_reason"] is None
    assert summary["target_envs"] == ["stage", "prod"]
    listed = next(
        row
        for row in list_plans(test_db, project="yoke", full=True)
        if row["id"] == plan["id"]
    )
    assert listed["materialized_requirement_count"] == 8


def test_a_release_forms_no_group_where_no_case_targets_its_environment(test_db):
    _item, plan, case = _setup(test_db)
    replace_plan_cases(test_db, plan_id=plan["id"], cases=[_production(case, ["prod"])])
    assert _release(test_db, plan["id"], "stage") == []
    assert run_groups(test_db, [RUNS["stage"]], "item-qa") == []
    assert len(_release(test_db, plan["id"], "prod")) == 1


def test_production_acceptance_cannot_close_an_unproven_stage_obligation(
    test_db, monkeypatch
):
    from yoke_core.domain import deployment_item_completion_runs as completion
    from yoke_core.domain.deployment_qa_plan_credit import plan_credit_misses

    _item, plan, _case = _setup(test_db)
    # A settled verification row, so the gate reaches the post-deploy plan.
    insert_qa_requirement(
        test_db,
        item_id=ITEM_ID,
        waived_at="2026-10-28T00:00:00Z",
        waiver_rationale="Not under test",
        waiver_source="operator",
    )
    _release(test_db, plan["id"], "prod")
    answering = {"prod": {"id": RUNS["prod"]}}
    # The credit read is under test: each environment's answering release.
    monkeypatch.setattr(
        completion,
        "latest_qa_member_run",
        lambda conn, *, item_id, target_env: answering.get(target_env),
    )
    _pass_group(test_db, RUNS["prod"])

    owed = plan_credit_misses(test_db, ITEM_ID)
    assert [(m["plan_slug"], m["deployment_run_id"]) for m in owed] == [(SLUG, None)]
    gate = check_done_gate(GateTarget(item_id=ITEM_ID), str(test_db.info.dsn))
    assert not gate.passed
    assert SLUG in "\n".join(gate.errors)

    _release(test_db, plan["id"], "stage")
    answering["stage"] = {"id": RUNS["stage"]}
    owed = plan_credit_misses(test_db, ITEM_ID)
    assert [(m["plan_slug"], m["deployment_run_id"]) for m in owed] == [
        (SLUG, RUNS["stage"])
    ]
    assert f"--deployment-run-id {RUNS['stage']}" in owed[0]["recovery"]

    _pass_group(test_db, RUNS["stage"])

    assert plan_credit_misses(test_db, ITEM_ID) == []
    gate = check_done_gate(GateTarget(item_id=ITEM_ID), str(test_db.info.dsn))
    assert gate.passed, gate.errors
    assert {(row["target_env"], row["item_id"]) for row in _rows(test_db)} == {
        ("prod", None),
        ("stage", None),
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
    item, _plan, _case = _setup(test_db, qa_phase="verification")
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
    _item, plan, case = _setup(test_db)
    replace_plan_cases(test_db, plan_id=plan["id"], cases=[_production(case, [])])
    assert _release(test_db, plan["id"], "stage") == []
    assert len(_release(test_db, plan["id"], "prod")) == 1
    (row,) = _rows(test_db)
    # A group row names the environment its release ran, the plan default here.
    assert row["target_env"] == "prod"
    assert _environment_of(row) == "prod"
