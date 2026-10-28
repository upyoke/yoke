"""A plan group runs as its own subject: separate per plan, one walk per release."""

import pytest

from runtime.api.domain.test_deployment_qa_plan_groups import (
    MEMBERS,
    RUN,
    SLUG,
    _attach,
    _seed,
)
from runtime.api.domain.test_deployment_qa_stage_execution import (
    _complete_case,
    _plan,
)
from yoke_core.domain.deployment_qa_plan_group_dispatch import settle_group
from yoke_core.domain.deployment_qa_plan_group_writes import (
    ensure_groups,
    group_subject,
)
from yoke_core.domain.deployment_qa_plan_groups import run_groups
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

OTHER = "other-plan"


def _begin(conn, plan=SLUG, session="plan-group-qa", member=None):
    return begin_plan_execution(
        conn,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
        plan=plan,
        actor_id="2",
        session_id=session,
    )


def _fail_case(conn, execution):
    """Walk the group's first case to a failing verdict and finish the walk."""
    from yoke_core.domain.qa_plan_execution_state import (
        advance_plan_execution,
        finish_plan_execution,
    )

    requirement_id = int(execution["roster"][0]["requirement_id"])
    now = "2026-10-28T00:00:01Z"
    run_id = conn.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,raw_result,"
        "started_at,completed_at,created_at) VALUES (%s,'worktree_run','plan_case',"
        "'fail','group probe failed',%s,%s,%s) RETURNING id",
        (requirement_id, now, now, now),
    ).fetchone()[0]
    advance_plan_execution(
        conn,
        execution,
        ordinal=0,
        requirement_id=requirement_id,
        result={
            "requirement_id": requirement_id,
            "verdict": "fail",
            "case_outcome": "failed",
            "run_id": int(run_id),
        },
    )
    finish_plan_execution(conn, execution, state="completed", reason="test-fail")
    return requirement_id


def _settle(conn, group):
    return settle_group(
        conn, group_subject(conn, RUN, "item-qa", group, require_active=False)
    )


def _groups(conn):
    return {group.plan_id: group for group in run_groups(conn, [RUN], "item-qa")}


def _two_plans(conn):
    """Every member attaches the smoke plan; only the last attaches the other plan."""
    smoke = _seed(conn)
    other = _plan(conn, OTHER)
    _attach(conn, MEMBERS[-1], other)
    ensure_groups(conn, RUN, "item-qa")
    conn.commit()
    return smoke, other


def test_each_attached_plan_forms_its_own_group_with_its_own_identity(test_db):
    smoke, other = _two_plans(test_db)

    groups = _groups(test_db)
    assert set(groups) == {smoke, other}
    assert groups[smoke].group_id != groups[other].group_id
    assert groups[smoke].digest != groups[other].digest
    for group in groups.values():
        deployment = group.target["deployment"]
        assert "member_item_id" not in deployment
        assert deployment["shared_plan"]["plan_id"] == group.plan_id


def test_a_failed_group_never_blocks_another_plan_s_group(test_db, monkeypatch):
    from yoke_core.domain import deployment_item_completion_runs as completion
    from yoke_core.domain.deployment_qa_plan_credit import plan_credit_misses

    monkeypatch.setattr(
        completion, "latest_qa_member_run", lambda conn, **_: {"id": RUN}
    )
    smoke, other = _two_plans(test_db)

    _complete_case(test_db, _begin(test_db))
    failing = _begin(test_db, OTHER, session="other-plan-qa")
    assert {row["plan_id"] for row in failing["roster"]} == {other}
    _fail_case(test_db, failing)
    groups = _groups(test_db)
    assert _settle(test_db, groups[smoke])["accepted"]
    assert not _settle(test_db, groups[other])["accepted"]

    groups = _groups(test_db)
    assert sorted(groups[smoke].covered_item_ids) == sorted(MEMBERS)
    assert groups[other].open
    for member in MEMBERS[:-1]:
        assert plan_credit_misses(test_db, member) == []
    assert [m["plan_slug"] for m in plan_credit_misses(test_db, MEMBERS[-1])] == [OTHER]


def test_two_groups_run_concurrently_each_in_its_own_session(test_db):
    smoke, other = _two_plans(test_db)

    first = _begin(test_db, session="smoke-qa")
    second = _begin(test_db, OTHER, session="other-qa")

    assert first["state"] == second["state"] == "active"
    assert first["id"] != second["id"]
    assert {row["plan_id"] for row in first["roster"]} == {smoke}
    assert {row["plan_id"] for row in second["roster"]} == {other}
    assert first["deployment_member_item_id"] is None
    assert second["deployment_member_item_id"] is None
    assert _begin(test_db, session="smoke-qa")["id"] == first["id"]
    assert _begin(test_db, OTHER, session="other-qa")["id"] == second["id"]


def test_a_second_session_cannot_take_a_held_group(test_db):
    from yoke_core.domain.qa_stage_execution_holders import StageRosterHeld

    _seed(test_db)
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    first = _begin(test_db, session="group-owner")

    with pytest.raises(StageRosterHeld, match=first["id"]):
        _begin(test_db, session="second-session")
    test_db.rollback()
    assert _begin(test_db, session="group-owner")["id"] == first["id"]


def test_an_attaching_member_named_on_begin_runs_the_one_group(test_db):
    _seed(test_db)
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()

    execution = _begin(test_db, member=MEMBERS[1])

    assert execution["deployment_member_item_id"] is None
    assert "member_item_id" not in execution["execution_target"]["deployment"]
    assert _begin(test_db, member=MEMBERS[0])["id"] == execution["id"]


def test_a_group_walk_survives_removals_until_its_last_attacher_leaves(test_db):
    from yoke_core.domain.qa_deployment_member_removal import (
        abort_removed_member_executions,
    )
    from yoke_core.domain.qa_plan_execution_store import select_plan_execution

    _seed(test_db)
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    execution = _begin(test_db)
    for index, member in enumerate(MEMBERS):
        test_db.execute(
            "DELETE FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
            (RUN, member),
        )
        abort_removed_member_executions(test_db, run_id=RUN, item_ids=(member,))
        test_db.commit()
        state = select_plan_execution(test_db, execution["id"], lock=False)["state"]
        assert state == ("aborted" if index == len(MEMBERS) - 1 else "active")


def test_group_execution_resolves_registered_project_and_review_policy(test_db):
    from uuid import uuid4

    from yoke_contracts.api.function_call import (
        ActorContext,
        FunctionCallRequest,
        TargetRef,
    )
    from yoke_core.domain.qa_deployment_function_subject import resolve_run_qa_subject
    from yoke_core.domain.qa_execution_request_identity import resolve_execution_request
    from yoke_core.domain.qa_review_verdict_modes import stage_review_verdicts

    _seed(test_db)
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    execution = _begin(test_db)
    request = FunctionCallRequest(
        function="qa.plan_execution.heartbeat",
        request_id=str(uuid4()),
        target=TargetRef(kind="global", project_id="yoke"),
        actor=ActorContext(actor_id="2", session_id="plan-group-qa"),
        payload={"execution_id": execution["id"]},
    )

    assert resolve_run_qa_subject(
        test_db, resolve_execution_request(test_db, request)
    ) == (1, "yoke", None)
    assert stage_review_verdicts(test_db, execution) == ("pass", "fail")


def test_a_declared_correction_keeps_the_group_and_credits_every_attacher(test_db):
    from yoke_core.domain.deployment_qa_stage_materialization import (
        materialize_deployment_qa_stage,
    )
    from yoke_core.domain.qa_requirement_correction_selection import (
        resolve_correction_selection,
    )
    from yoke_core.domain.qa_plan_management import replace_plan_cases
    from yoke_core.domain.qa_requirement_replacement import declare_replacements

    _seed(test_db)
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    (group,) = run_groups(test_db, [RUN], "item-qa")
    failed_id = _fail_case(test_db, _begin(test_db))
    assert not _settle(test_db, group)["accepted"]

    replace_plan_cases(
        test_db,
        plan_id=group.plan_id,
        cases=[
            {
                "case_key": "command-smoke",
                "position": 1,
                "method_id": "command",
                "instructions": "Run the corrected group probe.",
                "expected_outcome": "The corrected probe passes.",
                "method_config": {"command": "echo repaired"},
            }
        ],
    )
    replacements, scopes = resolve_correction_selection(
        test_db, [{"requirement_id": failed_id}]
    )
    materialized = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        agent_plan=SLUG,
        replacement_keys={entry["case_key"] for entry in replacements},
        replacement_scopes=scopes,
        replaced_requirement_ids=frozenset({failed_id}),
        commit=False,
    )
    corrected = [
        *materialized["created_requirement_ids"],
        *materialized["existing_requirement_ids"],
    ]
    declared = declare_replacements(
        test_db, replacements, materialized_requirement_ids=corrected
    )
    test_db.commit()
    assert declared[0]["requirement_id"] == failed_id

    (after,) = run_groups(test_db, [RUN], "item-qa")
    assert after.group_id == group.group_id and after.digest == group.digest
    execution = _begin(test_db, session="correction-qa")
    assert {row["requirement_id"] for row in execution["roster"]} <= set(
        after.requirement_ids
    )
    _complete_case(test_db, execution)
    assert _settle(test_db, after)["accepted"]
    (closed,) = run_groups(test_db, [RUN], "item-qa")
    assert sorted(closed.covered_item_ids) == sorted(MEMBERS)


def test_a_direct_group_case_run_names_the_group_plan_run(test_db):
    from yoke_core.domain.qa_case_execution_context import get_case_execution_context
    from yoke_core.domain.qa_case_stage_credit import item_scoped_stage_credit_refusal

    _seed(test_db)
    (requirement, *_rest) = ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    refusal = item_scoped_stage_credit_refusal(
        get_case_execution_context(test_db, requirement_id=requirement)
    )

    assert refusal is not None
    assert f"--deployment-run-id {RUN}" in refusal
    assert "--stage item-qa" in refusal
    assert "--plan" in refusal
    assert "--item" not in refusal
