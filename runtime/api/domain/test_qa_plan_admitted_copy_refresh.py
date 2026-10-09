"""Explicit item refresh reaches plan-backed copies without rewriting acceptance."""

import pytest

from runtime.api.domain.test_deployment_qa_admission_execution import (
    _environment,
    _seed_selected_requirement_run,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement, insert_qa_run
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_admitted_case_reconciliation import admitted_copies_in_flight
from yoke_core.domain.qa_plan_attachments import (
    attach_plan_to_item,
    materialize_for_item,
)
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_plan_management import (
    QaPlanError,
    create_plan,
    replace_plan_cases,
)
from yoke_core.domain.qa_plan_rematerialize import rematerialize_for_item

MEMBER = 7315
RUN = "run-plan-copy-refresh"
STAGE = "member-qa"


def _case(instructions="Run the admitted command."):
    return {
        "case_key": "admission-frame",
        "position": 1,
        "method_id": "command",
        "instructions": instructions,
        "expected_outcome": "The command passes.",
        "method_config": {"command": "true"},
        "target_envs": ["stage"],
    }


def _seed(conn):
    _environment(conn)
    item = insert_item(conn, id=MEMBER, workflow_id="issue", status="release")
    plan = create_plan(
        conn, project="yoke", slug="plan-copy-refresh", name="Plan copy refresh"
    )
    replace_plan_cases(conn, plan_id=plan["id"], cases=[_case()])
    attach_plan_to_item(
        conn,
        item_id=item["id"],
        plan_id=plan["id"],
        transition_id="release",
        qa_phase="post_deploy",
    )
    (source,) = materialize_for_item(conn, item_id=item["id"], transition_id="release")[
        "created_requirement_ids"
    ]
    _seed_selected_requirement_run(
        conn, run_id=RUN, item_id=MEMBER, requirement_id=source
    )
    materialize_deployment_qa_stage(
        conn,
        deployment_run_id=RUN,
        deployment_stage=STAGE,
        deployment_member_item_id=MEMBER,
    )
    copy = conn.execute(
        "SELECT id FROM qa_requirements WHERE deployment_run_id=%s AND plan_id=%s "
        "AND plan_case_key='admission-frame'",
        (RUN, plan["id"]),
    ).fetchone()["id"]
    assert copy != source
    return int(plan["id"]), int(source), int(copy)


def _definition(conn, requirement_id):
    return tuple(
        conn.execute(
            "SELECT instructions,method_config,execution_target_digest FROM qa_requirements WHERE id=%s",
            (requirement_id,),
        ).fetchone()
    )


def _edit(conn, plan_id):
    replace_plan_cases(
        conn, plan_id=plan_id, cases=[_case("Run the corrected command.")]
    )
    conn.commit()


def test_plan_edit_preserves_frozen_copy_until_explicit_refresh(test_db):
    plan, source, copy = _seed(test_db)
    before = _definition(test_db, copy)
    _edit(test_db, plan)
    assert _definition(test_db, copy) == before
    result = rematerialize_for_item(test_db, item_id=MEMBER, transition_id="release")
    assert result["refreshed_requirement_ids"] == [source]
    assert result["corrected_admitted_copy_ids"] == [copy]
    assert _definition(test_db, source)[0] == "Run the corrected command."
    assert _definition(test_db, copy)[0] == "Run the corrected command."
    assert _definition(test_db, copy)[2] == before[2]


@pytest.mark.parametrize("boundary", ["answered", "live_roster"])
def test_plan_copy_refresh_refuses_before_writing_source_or_copy(test_db, boundary):
    plan, source, copy = _seed(test_db)
    if boundary == "answered":
        insert_qa_run(test_db, qa_requirement_id=copy, verdict="fail")
    else:
        begin_plan_execution(
            test_db,
            deployment_run_id=RUN,
            deployment_stage=STAGE,
            deployment_member_item_id=MEMBER,
            actor_id="2",
            session_id="copy-walker",
        )
    before = [_definition(test_db, row) for row in (source, copy)]
    _edit(test_db, plan)
    with pytest.raises(QaPlanError, match="admitted_copy_in_flight") as refusal:
        rematerialize_for_item(test_db, item_id=MEMBER, transition_id="release")
    assert f"admitted case {copy}" in str(refusal.value)
    assert ("supersede" if boundary == "answered" else "yoke qa plan abort") in str(
        refusal.value
    )
    assert [_definition(test_db, row) for row in (source, copy)] == before


@pytest.mark.parametrize("boundary", ["terminal", "waived"])
def test_settled_or_terminal_plan_copy_keeps_its_original_definition(test_db, boundary):
    plan, source, copy = _seed(test_db)
    if boundary == "terminal":
        test_db.execute(
            "UPDATE deployment_runs SET status='succeeded' WHERE id=%s", (RUN,)
        )
    else:
        test_db.execute(
            "UPDATE qa_requirements SET waived_at=%s WHERE id=%s",
            (
                "2026-10-01T00:00:00Z",
                copy,
            ),
        )
    test_db.commit()
    before = _definition(test_db, copy)
    _edit(test_db, plan)
    result = rematerialize_for_item(test_db, item_id=MEMBER, transition_id="release")
    assert result["refreshed_requirement_ids"] == [source]
    assert result["corrected_admitted_copy_ids"] == []
    assert _definition(test_db, copy) == before


def test_plan_copy_identity_does_not_reach_other_members_baselines_or_environments(
    test_db,
):
    plan, source, copy = _seed(test_db)
    other = insert_item(test_db, title="Another plan member")
    for member, baseline, environment in (
        (other["id"], None, "stage"),
        (MEMBER, "separate", "stage"),
        (MEMBER, None, "prod"),
    ):
        insert_qa_requirement(
            test_db,
            item_id=None,
            deployment_run_id=RUN,
            deployment_stage=STAGE,
            deployment_member_item_id=member,
            plan_id=plan,
            plan_case_key="admission-frame",
            host_baseline=baseline,
            target_env=environment,
        )
    assert [
        row.requirement_id for row in admitted_copies_in_flight(test_db, source)
    ] == [copy]
    verification = insert_qa_requirement(
        test_db,
        item_id=MEMBER,
        plan_id=plan,
        plan_case_key="admission-frame",
        qa_phase="verification",
        target_env="stage",
    )
    assert admitted_copies_in_flight(test_db, verification["id"]) == []
