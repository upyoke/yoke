"""Identical attachments share execution without coupling other plans."""

import pytest

from runtime.api.domain.test_deployment_qa_stage_execution import (
    _complete_case,
    _plan,
    _seed_run,
    _stages,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_qa_run_acceptance import item_qa_acceptance_blockers
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_deployment_member_attached_plans import (
    delivery_answered_plan_ids,
)


RUN = "run-shared-plans"
MEMBERS = (9901, 9902)


def _seed(conn):
    plan_id = _plan(conn)
    stages = _stages(plan_id)
    stages[1].pop("cases")
    _seed_run(conn, run_id=RUN, stages=stages, members=MEMBERS)
    for member in MEMBERS:
        _attach(conn, member, plan_id)
    return plan_id


def _attach(conn, member, plan_id):
    conn.execute(
        "INSERT INTO qa_plan_item_attachments(item_id,plan_id,transition_id,qa_phase,attached_at) "
        "VALUES (%s,%s,'release','post_deploy','2026-10-14T00:00:00Z')",
        (member, plan_id),
    )
    conn.commit()


def _materialize(conn, member):
    return materialize_deployment_qa_stage(
        conn,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
    )


def _begin(conn, member):
    return begin_plan_execution(
        conn,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
        actor_id="2",
        session_id="shared-qa",
    )


def _fail(conn, requirement_id):
    conn.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,raw_result,started_at,completed_at,created_at) "
        "VALUES (%s,'worktree_run','plan_case','fail','shared probe failed',"
        "'2026-10-14T00:00:00Z','2026-10-14T00:00:01Z','2026-10-14T00:00:01Z')",
        (requirement_id,),
    )
    conn.commit()


@pytest.mark.parametrize("verdict", ["pass", "fail"])
def test_one_attachment_group_executes_once_and_answers_every_member(test_db, verdict):
    plan_id = _seed(test_db)
    first = _materialize(test_db, MEMBERS[0])
    second = _materialize(test_db, MEMBERS[1])
    assert len(first["created_requirement_ids"]) == 1
    assert second["created_requirement_ids"] == []
    assert second["existing_requirement_ids"] == first["created_requirement_ids"]
    execution = _begin(test_db, MEMBERS[0])
    assert _begin(test_db, MEMBERS[1])["id"] == execution["id"]
    assert execution["deployment_member_item_id"] is None
    assert "member_item_id" not in execution["execution_target"]["deployment"]
    requirement_id = _complete_case(test_db, execution)
    if verdict == "fail":
        _fail(test_db, requirement_id)
    for member in MEMBERS:
        result = deployment_qa_stage_status(
            test_db,
            run_id=RUN,
            stage_name="item-qa",
            member_item_id=member,
        )
        assert result["accepted"] is (verdict == "pass")
        assert bool(
            item_qa_acceptance_blockers(test_db, run_id=RUN, item_id=member)
        ) is (verdict == "fail")
        assert delivery_answered_plan_ids(
            test_db, member_item_id=member, plan_ids=[plan_id]
        ) == ({plan_id} if verdict == "pass" else set())
    if verdict == "pass":
        assert _begin(test_db, MEMBERS[1])["id"] == execution["id"]
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM qa_plan_executions WHERE deployment_run_id=%s", (RUN,)
        ).fetchone()[0]
        == 1
    )


def test_unrelated_plan_failure_does_not_block_the_other_attaching_member(test_db):
    _seed(test_db)
    other = _plan(test_db, "other-plan")
    _attach(test_db, MEMBERS[1], other)
    for member in MEMBERS:
        _materialize(test_db, member)
    _complete_case(test_db, _begin(test_db, MEMBERS[0]))
    assert not item_qa_acceptance_blockers(test_db, run_id=RUN, item_id=MEMBERS[0])
    assert item_qa_acceptance_blockers(test_db, run_id=RUN, item_id=MEMBERS[1])
    execution = _begin(test_db, MEMBERS[1])
    assert {row["plan_id"] for row in execution["roster"]} == {other}
    requirement_id = _complete_case(test_db, execution)
    _fail(test_db, requirement_id)
    assert not item_qa_acceptance_blockers(test_db, run_id=RUN, item_id=MEMBERS[0])
    assert item_qa_acceptance_blockers(test_db, run_id=RUN, item_id=MEMBERS[1])


@pytest.mark.parametrize("changed", ["plan", "source", "target"])
def test_shared_identity_keeps_different_groups_separate(changed):
    from copy import deepcopy
    from yoke_core.domain.deployment_qa_shared_plans import shared_subject
    from yoke_core.domain.qa_execution_environment_target import target_digest

    subject = {"member_item_id": 1}
    target = {
        "deployment": {"run_id": "run-example", "member_item_id": 1},
        "environment": {"name": "stage"},
    }
    snapshot = {"plan": {"id": 1, "source_revision": "a" * 40}}
    first = shared_subject(subject, target, snapshot)["shared_target"]
    other_target, other_plan = deepcopy(target), deepcopy(snapshot)
    if changed == "plan":
        other_plan["plan"]["id"] = 2
    elif changed == "source":
        other_plan["plan"]["source_revision"] = "b" * 40
    else:
        other_target["environment"]["name"] = "prod"
    second = shared_subject(subject, other_target, other_plan)["shared_target"]
    assert target_digest(first) != target_digest(second)
    target["deployment"]["member_item_id"] = 2
    assert shared_subject(subject, target, snapshot)["shared_target"] == first


def test_shared_execution_resolves_registered_project_and_review_policy(test_db):
    from uuid import uuid4
    from yoke_contracts.api.function_call import (
        FunctionCallRequest,
        TargetRef,
        ActorContext,
    )
    from yoke_core.domain.qa_deployment_function_subject import resolve_run_qa_subject
    from yoke_core.domain.qa_review_verdict_modes import stage_review_verdicts

    _seed(test_db)
    _materialize(test_db, MEMBERS[0])
    execution = _begin(test_db, MEMBERS[0])
    request = FunctionCallRequest(
        function="qa.plan_execution.heartbeat",
        request_id=str(uuid4()),
        target=TargetRef(kind="global", project_id="yoke"),
        actor=ActorContext(actor_id="2", session_id="shared-qa"),
        payload={"execution_id": execution["id"]},
    )
    from yoke_core.domain.qa_execution_request_identity import resolve_execution_request

    assert resolve_run_qa_subject(
        test_db, resolve_execution_request(test_db, request)
    ) == (1, "yoke", None)
    assert stage_review_verdicts(test_db, execution) == ("pass", "fail")


def test_refresh_reaches_shared_rows_through_either_attaching_member(test_db):
    from yoke_core.domain.qa_plan_management import replace_plan_cases
    from yoke_core.domain.qa_plan_rematerialize_deployment import (
        rematerialize_for_deployment_stage,
    )

    plan_id = _seed(test_db)
    first = _materialize(test_db, MEMBERS[0])["created_requirement_ids"]
    _fail(test_db, first[0])
    replace_plan_cases(
        test_db,
        plan_id=plan_id,
        cases=[
            {
                "case_key": "command-smoke",
                "method_id": "command",
                "instructions": "Run the corrected shared probe.",
                "expected_outcome": "The shared probe passes.",
                "method_config": {"command": "echo repaired"},
            }
        ],
    )
    result = rematerialize_for_deployment_stage(
        test_db,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBERS[1],
    )
    assert len(result["created_requirement_ids"]) == 1
    execution = _begin(test_db, MEMBERS[0])
    assert [row["requirement_id"] for row in execution["roster"]] == result[
        "created_requirement_ids"
    ]
    _complete_case(test_db, execution)
    assert all(
        not item_qa_acceptance_blockers(test_db, run_id=RUN, item_id=member)
        for member in MEMBERS
    )


def test_removing_one_member_preserves_shared_execution_until_last_member_leaves(
    test_db,
):
    from yoke_core.domain.qa_deployment_member_removal import (
        abort_removed_member_executions,
    )
    from yoke_core.domain.qa_plan_execution_store import select_plan_execution

    _seed(test_db)
    _materialize(test_db, MEMBERS[0])
    execution = _begin(test_db, MEMBERS[0])
    for index, member in enumerate(MEMBERS):
        test_db.execute(
            "DELETE FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
            (RUN, member),
        )
        abort_removed_member_executions(test_db, run_id=RUN, item_ids=(member,))
        test_db.commit()
        actual = select_plan_execution(test_db, execution["id"], lock=False)
        assert actual["state"] == ("active" if index == 0 else "aborted")


def test_declared_correction_preserves_shared_identity_and_credits_both(test_db):
    from yoke_core.domain.qa_requirement_correction_selection import (
        resolve_correction_selection,
    )
    from yoke_core.domain.qa_requirement_replacement import declare_replacements

    _seed(test_db)
    failed_id = _materialize(test_db, MEMBERS[0])["created_requirement_ids"][0]
    _fail(test_db, failed_id)
    corrected_plan = _plan(test_db, "corrected-shared-probe")
    replacements, scopes = resolve_correction_selection(
        test_db, [{"requirement_id": failed_id}]
    )
    materialized = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBERS[1],
        agent_plan=str(corrected_plan),
        replacement_keys={entry["case_key"] for entry in replacements},
        replacement_scopes=scopes,
        replaced_requirement_ids=frozenset({failed_id}),
        commit=False,
    )
    assert len(materialized["created_requirement_ids"]) == 1
    declared = declare_replacements(
        test_db,
        replacements,
        materialized_requirement_ids=materialized["created_requirement_ids"],
    )
    test_db.commit()
    assert declared[0]["requirement_id"] == failed_id
    execution = _begin(test_db, MEMBERS[0])
    assert {row["plan_id"] for row in execution["roster"]} == {corrected_plan}
    _complete_case(test_db, execution)
    assert all(
        not item_qa_acceptance_blockers(test_db, run_id=RUN, item_id=member)
        for member in MEMBERS
    )


def test_shared_direct_case_teaches_an_attaching_member_command(test_db):
    from yoke_core.domain.qa_case_execution_context import get_case_execution_context
    from yoke_core.domain.qa_case_stage_credit import item_scoped_stage_credit_refusal

    _seed(test_db)
    requirement = _materialize(test_db, MEMBERS[0])["created_requirement_ids"][0]
    context = get_case_execution_context(test_db, requirement_id=requirement)
    refusal = item_scoped_stage_credit_refusal(context)
    assert refusal is not None
    assert "--stage item-qa" in refusal
    assert "--item" in refusal
    assert "ATTACHING_MEMBER" in refusal
    assert "yoke qa plan get" in refusal
