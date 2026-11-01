"""A delivery settles without accepting an attached plan owed on another target."""

import json

import pytest

from runtime.api.domain.test_release_member_target_enrollment import _pair
from runtime.api.domain.test_post_deploy_original_pass_needs_admission import _record_evidence
from runtime.api.domain.test_status_transition_preflight import _isolate_status_effects
from runtime.api.fixtures.backlog_inserts import insert_qa_requirement
from yoke_core.domain.deployment_qa_plan_credit import plan_credit_misses
from yoke_core.domain.deployment_qa_stage_dispatch import materialize_and_gate_deployment_qa_stage
from yoke_core.domain.deployment_run_other_target_members import owes_only_other_targets
from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
from yoke_core.domain.no_obligation_member_close_out import satisfied_delivery_member
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.qa_plan_attachments import attach_plan_to_item

ITEM = 9788


def _plan_only_pair(conn, *, plan_environment="stage"):
    _pair(conn, item_id=ITEM)
    # Replace the fixture's ordinary intake with one standing plan. No own
    # requirement, snapshot case, or Production result may answer for it.
    conn.execute("DELETE FROM qa_requirements WHERE item_id=%s", (ITEM,))
    snapshot = json.dumps({
        "schema": 1, "requirements": [],
        "selection": {"schema": 1, "requirement_ids": [], "plan_ids": []},
    })
    conn.execute(
        "UPDATE deployment_run_items SET requirement_snapshot=%s,requirement_selection=NULL "
        "WHERE item_id=%s", (snapshot, ITEM),
    )
    plan = create_plan(conn, project="yoke", slug="other-target-plan",
                       target_environment=plan_environment)
    replace_plan_cases(conn, plan_id=int(plan["id"]), cases=[{
        "case_key": "only-case", "method_id": "command",
        "instructions": "Check behavior on the plan's declared target.",
        "expected_outcome": "The target passes its check.",
        "method_config": {"command": "true"},
        "target_envs": [plan_environment],
        "stage_reason": "creates_or_destroys_data",
    }])
    attach_plan_to_item(conn, plan_id=int(plan["id"]), item_id=ITEM,
                        transition_id="release", qa_phase="post_deploy")
    _record_evidence(conn, item_id=ITEM)
    conn.commit()
    return int(plan["id"])


def _gate(conn):
    stage = json.loads(conn.execute(
        "SELECT stages FROM deployment_flows WHERE id='flow-run-prod'",
    ).fetchone()[0])[1]
    return materialize_and_gate_deployment_qa_stage(conn, stage, run_id="run-prod")


def test_production_succeeds_without_accepting_the_single_stage_plan(test_db, monkeypatch):
    _isolate_status_effects(monkeypatch)
    plan = _plan_only_pair(test_db)
    assert _gate(test_db)[0] == 0
    assert satisfied_delivery_member(test_db, item_id=ITEM, run_id="run-prod")
    assert owes_only_other_targets(test_db, item_id=ITEM, run_id="run-prod")
    before = plan_credit_misses(test_db, ITEM)
    assert len(before) == 1 and before[0]["plan_id"] == plan

    assert cmd_update("run-prod", "status", "succeeded") is None

    assert test_db.execute(
        "SELECT status FROM deployment_runs WHERE id='run-prod'",
    ).fetchone()[0] == "succeeded"
    assert tuple(test_db.execute(
        "SELECT status,deployed_to FROM items WHERE id=%s", (ITEM,),
    ).fetchone()) == ("release", "prod")
    assert plan_credit_misses(test_db, ITEM) == before
    assert test_db.execute(
        "SELECT COUNT(*) FROM qa_runs r JOIN qa_requirements q ON q.id=r.qa_requirement_id "
        "WHERE q.plan_id=%s AND r.verdict='pass'", (plan,),
    ).fetchone()[0] == 0
    assert test_db.execute(
        "SELECT COUNT(*) FROM qa_requirements WHERE deployment_run_id='run-prod' "
        "AND deployment_member_item_id=%s", (ITEM,),
    ).fetchone()[0] == 0


def test_a_plan_owed_on_production_still_blocks_that_run(test_db, monkeypatch):
    _isolate_status_effects(monkeypatch)
    _plan_only_pair(test_db, plan_environment="prod")
    assert not satisfied_delivery_member(test_db, item_id=ITEM, run_id="run-prod")
    assert not owes_only_other_targets(test_db, item_id=ITEM, run_id="run-prod")
    assert cmd_update("run-prod", "status", "succeeded") is not None
    assert test_db.execute(
        "SELECT status FROM deployment_runs WHERE id='run-prod'",
    ).fetchone()[0] == "executing"


@pytest.mark.parametrize("attached", [False, True])
def test_an_unsettled_own_case_still_blocks_with_other_target_plan(test_db, attached):
    _plan_only_pair(test_db)
    if not attached:
        test_db.execute("DELETE FROM qa_plan_item_attachments WHERE item_id=%s", (ITEM,))
        test_db.commit()
    insert_qa_requirement(test_db, item_id=None, deployment_run_id="run-prod",
                          deployment_stage="member-qa", deployment_member_item_id=ITEM,
                          qa_phase="post_deploy", blocking_mode="blocking")
    assert not satisfied_delivery_member(test_db, item_id=ITEM, run_id="run-prod")
    assert not owes_only_other_targets(test_db, item_id=ITEM, run_id="run-prod")


def test_group_closed_during_this_presentation_is_immediately_satisfied(test_db):
    from runtime.api.domain.test_deployment_qa_plan_groups import MEMBERS, RUN, _seed, _pass_group
    from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups
    from yoke_core.domain.deployment_qa_plan_groups import covered_members
    from yoke_core.domain.deployment_qa_presentation_reads import presentation_operation

    plan = _seed(test_db)
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()

    @presentation_operation
    def close_and_read():
        assert covered_members(test_db, RUN, plan) == set()
        _pass_group(test_db)
        return satisfied_delivery_member(test_db, item_id=MEMBERS[0], run_id=RUN)

    assert close_and_read()


@pytest.mark.parametrize("missing_evidence", [False, True])
def test_other_target_notice_names_the_pending_group_without_hiding_failures(
    test_db, monkeypatch, tmp_path, missing_evidence,
):
    from runtime.api.domain.test_deployment_delivery_close_out_notice import _parked_owner
    from runtime.api.domain.test_deployment_qa_stage_wake_delivery import HOLDER_A, _project
    from runtime.api.fixtures.supplemental_credit import topology, pin
    from yoke_core.domain.deployment_qa_member_acceptance_notice import notify_item_qa_accepted
    from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups
    from yoke_core.domain.qa_done_gate_refusal import done_gate_refusal_errors

    _isolate_status_effects(monkeypatch)
    _project(test_db)
    _plan_only_pair(test_db)
    commits = topology(test_db, tmp_path, monkeypatch, ITEM)
    for run_id in ("run-prod", "run-stage"):
        pin(test_db, run_id, commits["landing"])
    test_db.execute(
        "UPDATE deployment_run_items SET delivery_intent='final' WHERE run_id='run-prod'",
    )
    ensure_groups(test_db, "run-stage", "member-qa")
    test_db.commit()
    assert _gate(test_db)[0] == 0
    _parked_owner(test_db, HOLDER_A, ITEM)
    if missing_evidence:
        from yoke_core.domain.item_json_sections import upsert_json_section

        upsert_json_section(test_db, item_id=ITEM, section="Execution Evidence", payload={}, ordering=0)
        test_db.commit()

    delivered = notify_item_qa_accepted(test_db, run_id="run-prod", item_id=ITEM)
    assert delivered in {"delivered", "undelivered"}
    [row] = test_db.execute(
        "SELECT body FROM session_messages WHERE idempotency_key LIKE %s",
        (f"release-wait-item-qa-accepted:{ITEM}:run-prod:%",),
    ).fetchall()
    body = row[0]
    if missing_evidence:
        assert "needs recovery" in body, body
        assert "yoke merge item" in body
        assert "Awaiting stage group" not in body
    else:
        assert "Awaiting stage group run-stage:1 on deployment run run-stage" in body
        assert "retries when that credit arrives" in body
        assert "failed" not in body and "needs recovery" not in body
        gate = "\n".join(done_gate_refusal_errors(
            test_db, plan_credit_misses(test_db, ITEM), name=str(ITEM),
        ))
        assert "stage group run-stage:1 on deployment run run-stage" in gate
        assert "on its completion run" not in gate
    assert test_db.execute("SELECT status FROM items WHERE id=%s", (ITEM,)).fetchone()[0] == "release"
