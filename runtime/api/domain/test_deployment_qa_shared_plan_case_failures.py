"""Shared-plan groups form only from shared attachments and read only their own rows."""

from runtime.api.domain.test_deployment_qa_shared_plans import (
    MEMBERS,
    RUN,
    _attach,
    _begin,
    _materialize,
    _seed,
)
from runtime.api.domain.test_deployment_qa_stage_execution import (
    _complete_case,
    _plan,
    _seed_run,
    _stages,
)
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)
from yoke_core.domain.deployment_qa_shared_plans import (
    member_plan_subjects,
    requirement_subject,
)
from yoke_core.domain.deployment_qa_stage_case_failures import (
    NO_CASES_FAILURE,
    case_failures,
)
from yoke_core.domain.deployment_qa_stage_contract import deployment_qa_stage_subject
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.qa_execution_environment_target import target_digest


def test_unmaterialized_group_does_not_borrow_another_groups_memberless_rows(
    test_db,
):
    shared_plan = _seed(test_db)
    shared_rows = _materialize(test_db, MEMBERS[0])["created_requirement_ids"]
    assert shared_rows
    other_plan = _plan(test_db, "other-plan")
    for member in MEMBERS:
        _attach(test_db, member, other_plan)
    subject = deployment_qa_stage_subject(
        test_db, run_id=RUN, stage_name="item-qa", member_item_id=MEMBERS[1]
    )
    groups = {
        group["shared_plan"]["plan_id"]: group
        for group in member_plan_subjects(
            test_db, subject, deployment_qa_execution_target(test_db, subject)
        )
    }
    assert set(groups) == {shared_plan, other_plan}

    def failures(plan_id):
        group = groups[plan_id]
        return case_failures(
            test_db,
            run_id=RUN,
            stage_name="item-qa",
            member_item_id=None,
            execution_target_digest=target_digest(
                deployment_qa_execution_target(test_db, group)
            ),
            shared_plan_id=plan_id,
        )

    assert failures(other_plan) == [NO_CASES_FAILURE]
    assert {failure.requirement_id for failure in failures(shared_plan)} == set(
        shared_rows
    )

    status = deployment_qa_stage_status(
        test_db, run_id=RUN, stage_name="item-qa", member_item_id=MEMBERS[1]
    )
    assert status["accepted"] is False
    named = " ".join(str(reason) for reason in status.get("reasons") or [])
    assert "None" not in named


def test_plan_attached_by_one_member_stays_that_members_private_copy(test_db):
    single = _plan(test_db)
    stages = _stages(single)
    stages[1].pop("cases")
    _seed_run(test_db, run_id=RUN, stages=stages, members=MEMBERS)
    _attach(test_db, MEMBERS[1], single)
    (requirement_id,) = _materialize(test_db, MEMBERS[1])["created_requirement_ids"]
    owner = test_db.execute(
        "SELECT deployment_member_item_id FROM qa_requirements WHERE id=%s",
        (requirement_id,),
    ).fetchone()[0]
    assert owner == MEMBERS[1]
    subject = requirement_subject(test_db, requirement_id)
    assert subject["member_item_id"] == MEMBERS[1]
    assert subject["stage"]["scope"] == "item"

    execution = _begin(test_db, MEMBERS[1])
    assert execution["deployment_member_item_id"] == MEMBERS[1]
    assert _complete_case(test_db, execution) == requirement_id
    assert deployment_qa_stage_status(
        test_db, run_id=RUN, stage_name="item-qa", member_item_id=MEMBERS[1]
    )["accepted"]


def test_removing_the_last_attaching_member_retracts_the_shared_copy(test_db):
    from yoke_core.domain.deployment_run_member_removal import remove_member_on

    _seed(test_db)
    (requirement_id,) = _materialize(test_db, MEMBERS[0])["created_requirement_ids"]

    def retracted_at():
        return test_db.execute(
            "SELECT retracted_at FROM qa_requirements WHERE id=%s", (requirement_id,)
        ).fetchone()[0]

    remove_member_on(test_db, RUN, MEMBERS[0], reason="split out of the release")
    assert retracted_at() is None
    remove_member_on(test_db, RUN, MEMBERS[1], reason="split out of the release")
    assert retracted_at() is not None


def test_orphan_check_reads_peers_once_and_refreshes_after_each_removal(test_db):
    from runtime.api.domain.test_deployment_shipping_reads import CountedConnection
    from yoke_core.domain.qa_deployment_member_removal import (
        _plan_still_attached,
        retract_orphaned_shared_copies,
    )
    from yoke_core.domain.schema_read_scope import composition_reads

    members = (9901, 9902, 9903)
    plan = _plan(test_db, "orphan-read-scope")
    stages = _stages(plan)
    stages[1].pop("cases")
    _seed_run(test_db, run_id=RUN, stages=stages, members=members)
    for member in members:
        _attach(test_db, member, plan)
    (requirement,) = _materialize(test_db, members[0])["created_requirement_ids"]
    conn = CountedConnection(test_db)

    # Create already shares schema/source reads across all membership writes.
    with composition_reads():
        assert _plan_still_attached(conn, RUN, "item-qa", plan)
        peer_reads = sum(
            count
            for sql, count in conn.queries.items()
            if "SELECT item_id,requirement_snapshot FROM deployment_run_items" in sql
        )
        assert peer_reads == 1
        for index, member in enumerate(members):
            conn.execute(
                "DELETE FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
                (RUN, member),
            )
            assert _plan_still_attached(conn, RUN, "item-qa", plan) is (index < 2)
            retracted = retract_orphaned_shared_copies(
                conn, run_id=RUN, reason="member moved to a later release"
            )
            assert retracted == ([] if index < 2 else [requirement])
