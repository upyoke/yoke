"""Presentation batching preserves unrun cases and live withdrawal authority."""

from runtime.api.domain.test_deployment_qa_admission_execution import (
    _original_requirement,
)
from runtime.api.domain.test_deployment_qa_stage_execution import (
    _plan,
    _seed_run,
    _stages,
)
from runtime.api.domain.test_deployment_qa_shared_plans import _attach
from runtime.api.domain.test_deployment_shipping_reads import CountedConnection
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.deployment_qa_frozen_plan_selection import member_requirements
from yoke_core.domain.deployment_qa_presentation_reads import presentation_operation
from yoke_core.domain.deployment_qa_presentation_facts import member_presentation
from yoke_core.domain.deployment_qa_run_acceptance import (
    current_item_qa,
    member_qa_standings,
)
from yoke_core.domain.deployment_qa_stage_contract import deployment_qa_stage_subject
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_requirement_snapshots import (
    snapshot_member_requirements,
    requirement_selection,
)


def test_frozen_source_withdrawal_is_equivalent_and_request_scoped(test_db):
    members = (31001, 31002, 31003)
    source_ids = []
    for member in members:
        insert_item(test_db, id=member, project_sequence=member, status="done")
        source_ids.append(
            _original_requirement(test_db, item_id=member, method_id=None)
        )
    _seed_run(
        test_db,
        run_id="withdrawal-read",
        stages=_stages(_plan(test_db)),
        members=(),
        existing_members=members,
    )
    subjects = [("withdrawal-read", member, "item-qa") for member in members]
    for member, source in zip(members, source_ids):
        snapshot = snapshot_member_requirements(
            test_db,
            run_id="withdrawal-read",
            item_id=member,
            selection_json=requirement_selection(requirement_ids=[source]),
        )
        test_db.execute(
            "UPDATE deployment_run_items SET requirement_snapshot=%s "
            "WHERE run_id=%s AND item_id=%s",
            (snapshot, "withdrawal-read", member),
        )

    def read(conn, selected):
        result = {}
        for run, member, stage in selected:
            subject = deployment_qa_stage_subject(
                conn,
                run_id=run,
                stage_name=stage,
                member_item_id=member,
                require_active=False,
            )
            result[member] = member_requirements(
                conn, subject, target=deployment_qa_execution_target(conn, subject)
            )
        return result

    batched = presentation_operation(member_presentation(read))
    before = batched(test_db, subjects)
    assert before == read(test_db, subjects)
    assert all(before[member] for member in members)
    test_db.execute(
        "UPDATE qa_requirements SET retracted_at=%s WHERE id=%s",
        ("2026-09-15T00:00:00Z", source_ids[0]),
    )
    after = batched(test_db, subjects)
    assert after == read(test_db, subjects)
    assert after[members[0]] == []
    assert after[members[1]] == before[members[1]]


def test_private_unrun_member_answers_match_scalar_authority(test_db):
    flow_plan = _plan(test_db, "private-display-flow")
    stages = _stages(flow_plan)
    stages[1].pop("cases")
    members = tuple(range(32001, 32021))
    _seed_run(test_db, run_id="private-unrun", stages=stages, members=members)
    for member in members:
        _attach(test_db, member, _plan(test_db, f"private-check-{member}"))
    subjects = [("private-unrun", member, "item-qa") for member in members]
    unmaterialized = CountedConnection(test_db)
    before = member_qa_standings(unmaterialized, subjects)
    assert all(answer["state"] == "not yet run" for answer in before.values())
    print(
        f"Shipping unmaterialized: members=20 queries={sum(unmaterialized.queries.values())} "
        f"callers={unmaterialized.callers.most_common(20)}"
    )
    assert sum(unmaterialized.queries.values()) < 30
    for member in members:
        materialize_deployment_qa_stage(
            test_db,
            deployment_run_id="private-unrun",
            deployment_stage="item-qa",
            deployment_member_item_id=member,
        )
    conn = CountedConnection(test_db)
    answers = member_qa_standings(conn, subjects)
    assert all(answer["state"] == "not yet run" for answer in answers.values())
    for run, member, stage in subjects:
        expected = current_item_qa(
            test_db, run_id=run, item_id=member, current_stage=stage
        )
        assert answers[(run, member)] == {
            "state": expected.state,
            "stage": expected.stage,
            "reason": expected.reason,
            "failed_requirement_ids": list(expected.failed_requirement_ids),
        }
    print(
        f"Shipping private/unrun: members=20 queries={sum(conn.queries.values())} "
        f"callers={conn.callers.most_common(20)}"
    )
    assert sum(conn.queries.values()) < 30


def test_pending_independent_review_remains_pending_then_refreshes(test_db):
    from runtime.api.domain.test_qa_capture_pending_review import (
        _seed_pending,
        _submit,
        MEMBER,
        STAGE,
    )

    run = "shipping-review-pending"
    execution, bundle, requirement = _seed_pending(test_db, run, "item")
    subjects = [(run, MEMBER, STAGE)]
    pending = member_qa_standings(test_db, subjects)[(run, MEMBER)]
    expected = current_item_qa(test_db, run_id=run, item_id=MEMBER, current_stage=STAGE)
    assert pending["state"] == expected.state == "awaiting review"
    assert pending["reason"] == expected.reason
    _submit(test_db, execution, bundle, requirement, "pass")
    assert member_qa_standings(test_db, subjects)[(run, MEMBER)]["state"] == "accepted"


def test_case_environment_overrides_share_reads_and_refresh_next_request(test_db):
    import json
    from runtime.api.domain.test_deployment_qa_stage_execution import _environment
    from yoke_core.domain.qa_deployment_member_attached_plans import (
        attached_member_plan_ids,
    )

    _environment(test_db)
    plan = _plan(test_db, "cross-environment-display", target_envs=["stage"])
    members = tuple(range(33001, 33021))
    _seed_run(
        test_db, run_id="cross-environment-read", stages=_stages(plan), members=members
    )
    stage = test_db.execute(
        "SELECT id FROM environments WHERE name='stage'"
    ).fetchone()[0]
    other = test_db.execute(
        "INSERT INTO environments(site,project_id,name,url,settings,created_at) "
        "SELECT site,project_id,'other','https://other.example.test','{}',created_at "
        "FROM environments WHERE id=%s RETURNING id",
        (stage,),
    ).fetchone()[0]
    test_db.execute(
        "UPDATE qa_plans SET target_environment_id=%s WHERE id=%s", (other, plan)
    )
    for member in members:
        _attach(test_db, member, plan)

    @presentation_operation
    @member_presentation
    def read(conn, subjects):
        return [
            attached_member_plan_ids(conn, member_item_id=member, environment_id=stage)
            for _, member, _ in subjects
        ]

    subjects = [("cross-environment-read", member, "item-qa") for member in members]
    conn = CountedConnection(test_db)
    assert read(conn, subjects) == [[plan]] * len(members)
    assert (
        sum(
            n
            for sql, n in conn.queries.items()
            if "SELECT name FROM environments" in sql
        )
        == 1
    )
    assert (
        sum(n for sql, n in conn.queries.items() if "FROM qa_plan_cases c" in sql) == 1
    )
    test_db.execute(
        "UPDATE qa_plan_cases SET target_envs=%s WHERE plan_id=%s",
        (json.dumps(["other"]), plan),
    )
    assert read(conn, subjects) == [[]] * len(members)
