"""Carried members owe item QA only when their own flow or cases require it."""

import json
from yoke_contracts.timestamps import parse_instant

import pytest

from runtime.api.domain.coordination_claim_test_support import seed_project
from runtime.api.domain.test_deployment_qa_stage_execution import (
    _complete_case,
    _plan,
    _seed_run,
    _stages,
)
from runtime.api.domain.test_no_obligation_member_close_out import (
    _landing_evidence,
)
from runtime.api.domain.test_status_transition_preflight import _isolate_status_effects
from runtime.api.fixtures.backlog_inserts import insert_item, insert_qa_requirement
from yoke_core.domain.deployment_delivery_close_out_notice import (
    notify_delivery_cleared,
)
from yoke_core.domain.deployment_qa_stage_acceptance import stage_acceptance
from yoke_core.domain.deployment_qa_stage_contract import deployment_qa_stage_subject
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)
from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_gate import (
    ACCEPTANCE_QA_KIND,
    deployment_qa_stage_status,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_outstanding import qa_stage_outstanding
from yoke_core.domain.deployment_qa_stage_prerequisites import (
    prior_stage_refusals,
    require_prior_stage_acceptance,
)
from yoke_core.domain.deployment_requirement_snapshots import (
    requirement_selection,
    snapshot_member_requirements,
)
from yoke_core.domain.post_deploy_verification_answer import answer_for_item
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.steering_fleet_report_deployment_runs import run_progress

RUN = "run-carried-item-qa"
MEMBER = 9951
OTHER = 995
OWN_FLOW = "carried-completion"


def _ready(conn, *, own_qa=False, same_project=False, cases=False, follow_stage=False):
    seed_project(conn, OTHER, "carried")
    site = conn.execute(
        "INSERT INTO sites(project_id,name,created_at) VALUES (%s,'app','2026-10-01T00:00:00Z') RETURNING id",
        (OTHER,),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO environments(site,project_id,name,url,created_at) VALUES (%s,%s,'prod','https://carried.example.test','2026-10-01T00:00:00Z')",
        (site, OTHER),
    )
    plan = _plan(conn)
    stages = _stages(plan)
    if not cases:
        stages[1].pop("cases")
    if follow_stage:
        stages.append({**stages[1], "name": "later-item-qa"})
    own_stages = [stages[1]] if own_qa else []
    conn.execute(
        "INSERT INTO deployment_flows(id,project_id,name,stages,created_at) "
        "VALUES (%s,%s,%s,%s,'2026-10-01T00:00:00Z')",
        (OWN_FLOW, OTHER, OWN_FLOW, json.dumps(own_stages)),
    )
    insert_item(
        conn,
        id=MEMBER,
        project_id=1 if same_project else OTHER,
        workflow_id="dash",
        status="release",
        deployment_flow=OWN_FLOW,
    )
    _seed_run(conn, run_id=RUN, stages=stages, members=(), existing_members=(MEMBER,))
    conn.execute(
        "INSERT INTO environments(site,project_id,name,url,created_at) "
        "VALUES (%s,%s,'stage','https://carried.example.test','2026-10-01T00:00:00Z')",
        (site, OTHER),
    )
    # This command-only producer does not observe a browser endpoint.
    conn.execute(
        "UPDATE deployment_stage_receipts SET observed_url=NULL WHERE run_id=%s",
        (RUN,),
    )
    conn.execute(
        "UPDATE deployment_runs SET bound_sources=%s WHERE id=%s",
        (
            json.dumps(
                {
                    "schema": 1,
                    "projects": [{"project_id": OTHER, "commit_sha": "b" * 40}],
                }
            ),
            RUN,
        ),
    )
    conn.commit()
    return stages[1]


def _materialize(conn):
    return materialize_deployment_qa_stage(
        conn,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER,
    )


def _status(conn):
    return deployment_qa_stage_status(
        conn, run_id=RUN, stage_name="item-qa", member_item_id=MEMBER
    )


def test_carried_member_without_own_item_qa_is_settled_and_closes(test_db, monkeypatch):
    _isolate_status_effects(monkeypatch)
    stage = _ready(test_db)
    assert answer_for_item(test_db, MEMBER).unanswered
    result = _materialize(test_db)
    assert result["created_requirement_ids"] == []
    assert result["declared_no_post_deploy_verification"] == []
    assert OWN_FLOW in result["no_item_qa_obligation"][0]
    status = _status(test_db)
    assert status["accepted"] and status["outcome"] == "discharged"
    assert "cross-project" in status["reasons"][0]
    subject = deployment_qa_stage_subject(
        test_db, run_id=RUN, stage_name="item-qa", member_item_id=MEMBER
    )
    accepted = stage_acceptance(
        test_db,
        subject=subject,
        target=deployment_qa_execution_target(test_db, subject),
        acceptance_qa_kind=ACCEPTANCE_QA_KIND,
    )
    assert accepted.accepted
    outstanding = qa_stage_outstanding(test_db, run_id=RUN, stage_name="item-qa")
    assert outstanding.waiting == 0 and outstanding.waiting_members == ()
    assert "no item QA obligation" in outstanding.no_obligation_lines[0]
    [report] = run_progress(
        test_db, project_id=1, now=parse_instant("2026-10-02T00:00:00Z")
    )
    assert report.outstanding == 0
    assert report.no_obligation_lines == outstanding.no_obligation_lines
    assert materialize_and_gate_deployment_qa_stage(test_db, stage, run_id=RUN) == (
        0,
        "",
    )
    _landing_evidence(test_db, MEMBER)
    test_db.execute("UPDATE deployment_runs SET status='succeeded' WHERE id=%s", (RUN,))
    test_db.commit()
    [closed] = notify_delivery_cleared(test_db, run_id=RUN)
    assert closed["delivery"] == "closed"
    assert (
        test_db.execute("SELECT status FROM items WHERE id=%s", (MEMBER,)).fetchone()[0]
        == "done"
    )
    assert answer_for_item(test_db, MEMBER).unanswered


def test_exempt_carried_member_does_not_block_a_later_item_qa_stage(test_db):
    stage = _ready(test_db, follow_stage=True)
    stages = [stage, {**stage, "name": "later-item-qa"}]
    assert answer_for_item(test_db, MEMBER).unanswered
    assert (
        prior_stage_refusals(
            test_db, run_id=RUN, stages=stages, start_stage="later-item-qa"
        )
        == []
    )
    require_prior_stage_acceptance(
        test_db, run_id=RUN, stages=stages, start_stage="later-item-qa"
    )


@pytest.mark.parametrize("own_qa,same_project", [(True, False), (False, True)])
def test_unanswered_members_still_hold_the_stage(test_db, own_qa, same_project):
    stage = _ready(test_db, own_qa=own_qa, same_project=same_project)
    code, reason = materialize_and_gate_deployment_qa_stage(test_db, stage, run_id=RUN)
    assert code == -4 and "no pinned cases" in reason
    assert not _status(test_db)["accepted"]
    outstanding = qa_stage_outstanding(test_db, run_id=RUN, stage_name="item-qa")
    assert outstanding.waiting_members == (MEMBER,)
    assert outstanding.no_obligation_lines == ()


@pytest.mark.parametrize(
    "obligation", ["attachment", "requirement", "run_case", "flow_cases"]
)
def test_explicit_cases_survive_own_flow_without_item_qa(test_db, obligation):
    _ready(test_db, cases=obligation == "flow_cases")
    if obligation == "attachment":
        plan = create_plan(
            test_db,
            project="carried",
            slug="member-smoke",
            name="Member smoke",
            infer_target_environment=False,
        )
        replace_plan_cases(
            test_db,
            plan_id=int(plan["id"]),
            cases=[
                {
                    "case_key": "member-check",
                    "position": 1,
                    "method_id": "command",
                    "instructions": "Check the carried member",
                    "expected_outcome": "passes",
                    "method_config": {"command": "true"},
                }
            ],
        )
        test_db.execute(
            "INSERT INTO qa_plan_item_attachments(plan_id,item_id,transition_id,qa_phase,attached_at) "
            "VALUES (%s,%s,'release','post_deploy','2026-10-01T00:00:00Z')",
            (int(plan["id"]), MEMBER),
        )
    elif obligation in {"requirement", "run_case"}:
        kwargs = (
            {"item_id": MEMBER}
            if obligation == "requirement"
            else {
                "item_id": None,
                "deployment_run_id": RUN,
                "deployment_stage": "item-qa",
                "deployment_member_item_id": MEMBER,
            }
        )
        insert_qa_requirement(
            test_db,
            **kwargs,
            method_id="command",
            method_name="Command",
            runner_id="worktree_run",
            verdict_path="automatic",
            capability_requirements="[]",
            qa_phase="post_deploy",
            blocking_mode="blocking",
            instructions="Check the carried member",
            expected_outcome="passes",
            method_config=json.dumps({"command": "true"}),
        )
    if obligation == "requirement":
        requirement = test_db.execute(
            "SELECT id FROM qa_requirements WHERE item_id=%s", (MEMBER,)
        ).fetchone()[0]
        snapshot = snapshot_member_requirements(
            test_db,
            run_id=RUN,
            item_id=MEMBER,
            selection_json=requirement_selection(requirement_ids=[requirement]),
        )
        test_db.execute(
            "UPDATE deployment_run_items SET requirement_snapshot=%s WHERE run_id=%s AND item_id=%s",
            (snapshot, RUN, MEMBER),
        )
    test_db.commit()
    result = _materialize(test_db)
    assert result["created_requirement_ids"] or result["existing_requirement_ids"]
    assert result["no_item_qa_obligation"] == []
    assert not _status(test_db)["accepted"]
    assert qa_stage_outstanding(
        test_db, run_id=RUN, stage_name="item-qa"
    ).waiting_members == (MEMBER,)
    execution = begin_plan_execution(
        test_db,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER,
        actor_id="2",
        session_id="member-qa",
    )
    _complete_case(test_db, execution)
    assert _status(test_db)["accepted"]
