"""Plan-group identity, pinning, defaults, notices and acceptance, asserted on data."""

from unittest import mock

import pytest

from runtime.api.domain.test_deployment_qa_plan_groups import (
    MEMBERS,
    RUN,
    SLUG,
    _attach,
    _begin,
    _pass_group,
    _seed,
)
from runtime.api.domain.test_deployment_qa_stage_execution import (
    _complete_case,
    _plan,
    _seed_run,
    _stages,
)
from runtime.api.fixtures.deployment_run_driver_fixture import DRIVER_SESSION
from yoke_core.domain.deployment_qa_plan_credit import plan_credit_misses
from yoke_core.domain.deployment_qa_plan_group_dispatch import (
    gate_plan_groups,
    settle_group,
)
from yoke_core.domain.deployment_qa_plan_group_writes import (
    ensure_groups,
    group_subject,
)
from yoke_core.domain.deployment_qa_plan_groups import (
    retract_unattached_groups,
    run_groups,
)

WAIT_KEYS = "deployment-qa-stage-wait:" + RUN + ":item-qa:plan-groups:%"


def _form(conn):
    created = ensure_groups(conn, RUN, "item-qa")
    conn.commit()
    return created


def _pin_flow(conn, members=MEMBERS):
    conn.execute(
        "UPDATE items SET deployment_flow=%s WHERE id=ANY(%s)", (f"flow-{RUN}", list(members))
    )
    conn.commit()


def test_a_retracted_group_is_never_reused_by_a_later_attacher(test_db):
    plan_id = _seed(test_db)
    _form(test_db)
    (first,) = run_groups(test_db, [RUN], "item-qa")
    test_db.execute("DELETE FROM qa_plan_item_attachments WHERE plan_id=%s", (plan_id,))
    test_db.commit()
    retracted = retract_unattached_groups(test_db, RUN, reason="detached", source="test")
    test_db.commit()
    assert sorted(retracted) == sorted(first.requirement_ids)

    _attach(test_db, MEMBERS[0], plan_id)
    created = _form(test_db)

    old, new = run_groups(test_db, [RUN], "item-qa")
    assert old.group_id == first.group_id and old.retracted and not old.closed
    assert new.group_id == f"{RUN}:2" and new.open and new.digest != old.digest
    assert sorted(new.requirement_ids) == sorted(created)
    assert set(new.requirement_ids).isdisjoint(old.requirement_ids)


def test_re_attaching_a_plan_after_its_group_passed_keeps_the_credit(test_db):
    plan_id = _seed(test_db)
    _pin_flow(test_db)
    _form(test_db)
    _pass_group(test_db)
    test_db.execute(
        "DELETE FROM qa_plan_item_attachments WHERE item_id=%s AND plan_id=%s",
        (MEMBERS[0], plan_id),
    )
    test_db.execute(
        "INSERT INTO qa_plan_item_attachments(item_id,plan_id,transition_id,qa_phase,"
        "attached_at) VALUES (%s,%s,'release','post_deploy','2026-10-29T00:00:00Z')",
        (MEMBERS[0], plan_id),
    )
    test_db.commit()

    assert _form(test_db) == []
    (group,) = run_groups(test_db, [RUN], "item-qa")
    assert group.closed and MEMBERS[0] in group.covered_item_ids
    assert plan_credit_misses(test_db, MEMBERS[0]) == []


def test_a_project_default_only_plan_forms_a_group_and_is_credited(test_db):
    plan_id = _seed(test_db, attached=())
    test_db.execute(
        "INSERT INTO qa_plan_project_defaults(project_id,workflow_id,transition_id,"
        "plan_id,qa_phase,attached_at) VALUES (1,'issue','release',%s,'post_deploy',"
        "'2026-10-28T00:00:00Z')",
        (plan_id,),
    )
    test_db.commit()
    _pin_flow(test_db)
    assert test_db.execute(
        "SELECT COUNT(*) FROM qa_plan_item_attachments WHERE plan_id=%s", (plan_id,)
    ).fetchone()[0] == 0
    assert [m["plan_slug"] for m in plan_credit_misses(test_db, MEMBERS[0])] == [SLUG]

    _form(test_db)
    (group,) = run_groups(test_db, [RUN], "item-qa")
    assert group.plan_id == plan_id and group.open
    _pass_group(test_db)

    (group,) = run_groups(test_db, [RUN], "item-qa")
    assert group.covered_item_ids == tuple(sorted(MEMBERS))
    for member in MEMBERS:
        assert plan_credit_misses(test_db, member) == []


def _case_rows(conn, ids):
    return [
        (row[0], str(row[1]))
        for row in conn.execute(
            "SELECT plan_case_key,method_config FROM qa_requirements WHERE id=ANY(%s) "
            "ORDER BY plan_case_key",
            (list(ids),),
        ).fetchall()
    ]


def test_a_second_group_in_the_run_uses_the_pinned_plan_after_an_edit(test_db):
    from yoke_core.domain.qa_plan_management import replace_plan_cases

    plan_id = _seed(test_db, attached=MEMBERS[:2])
    _form(test_db)
    (first,) = run_groups(test_db, [RUN], "item-qa")
    pinned = _case_rows(test_db, first.requirement_ids)
    replace_plan_cases(
        test_db,
        plan_id=plan_id,
        cases=[
            {
                "case_key": "edited-smoke",
                "position": 1,
                "method_id": "command",
                "instructions": "run the edited smoke command",
                "expected_outcome": "the edited command passes",
                "method_config": {"command": "echo edited"},
            }
        ],
    )
    test_db.commit()
    assert _case_rows(test_db, first.requirement_ids) == pinned  # open group unchanged
    _pass_group(test_db)
    _attach(test_db, MEMBERS[2], plan_id)

    created = _form(test_db)

    first, second = run_groups(test_db, [RUN], "item-qa")
    assert second.group_id == f"{RUN}:2" and sorted(second.requirement_ids) == sorted(created)
    assert _case_rows(test_db, second.requirement_ids) == pinned
    marker = second.target["deployment"]["shared_plan"]
    assert marker["source_revision"] == first.target["deployment"]["shared_plan"]["source_revision"]


def test_a_candidate_lacking_the_plan_source_forms_no_group_and_names_it(
    test_db, monkeypatch
):
    from yoke_core.domain import qa_plan_source_revision as source_binding
    from yoke_core.domain.qa_plan_management import QaPlanError

    plan_id = _seed(test_db)
    revision = "c" * 40
    test_db.execute("UPDATE qa_plans SET source_revision=%s WHERE id=%s", (revision, plan_id))
    test_db.commit()
    source = mock.Mock()
    source.resolve_commit.side_effect = lambda value: value
    source.contains_commit.return_value = False
    monkeypatch.setattr(source_binding, "open_carried_work_source", lambda *_: source)

    with pytest.raises(QaPlanError, match="qa_plan_source_candidate_mismatch") as refusal:
        ensure_groups(test_db, RUN, "item-qa")
    test_db.rollback()

    assert revision in str(refusal.value) and f"plan {plan_id}" in str(refusal.value)
    assert run_groups(test_db, [RUN]) == []
    assert test_db.execute(
        "SELECT COUNT(*) FROM qa_requirements WHERE plan_id=%s", (plan_id,)
    ).fetchone()[0] == 0


def _wait_messages(conn):
    return conn.execute(
        "SELECT idempotency_key,body FROM session_messages WHERE idempotency_key LIKE %s "
        "ORDER BY created_at",
        (WAIT_KEYS,),
    ).fetchall()


def _manual_plan(conn, plan_id):
    conn.execute(
        "UPDATE qa_plan_cases SET wake_path='manual', "
        "wake_evidence='a production traffic sample is recorded for this release' "
        "WHERE plan_id=%s",
        (plan_id,),
    )
    conn.commit()


def _dispatch(conn):
    stage = {"name": "item-qa", "scope": "item"}
    return gate_plan_groups(conn, stage, run_id=RUN, project_id=1, item_refs=str)


def test_an_unchanged_dispatch_sends_no_second_notice_and_a_new_group_re_sends(test_db):
    from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
        _project,
        _recipients,
        seed_session,
    )
    from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver
    from yoke_core.domain.deployment_run_driver_attachment import (
        PHASE_EXECUTING,
        attach_driver,
    )

    plan_id = _seed(test_db)
    _manual_plan(test_db, plan_id)
    _project(test_db)
    seed_session(test_db, "sess-plan-driver")
    release_seeded_driver(test_db, RUN)
    attach_driver(test_db, RUN, session_id="sess-plan-driver", pid=4243, phase=PHASE_EXECUTING)
    test_db.commit()
    _form(test_db)

    assert _dispatch(test_db)
    assert _dispatch(test_db)
    (first,) = _wait_messages(test_db)
    assert f"--plan {SLUG}" in first[1]

    other = _plan(test_db, "other-plan")
    _manual_plan(test_db, other)
    _attach(test_db, MEMBERS[0], other)
    _form(test_db)
    _dispatch(test_db)
    _dispatch(test_db)

    messages = _wait_messages(test_db)
    assert len(messages) == 2 and messages[1][0] != first[0]
    assert _recipients(test_db, messages[1][0]) == ["sess-plan-driver"]
    assert f"--plan {SLUG}" in messages[1][1] and "--plan other-plan" in messages[1][1]


def test_the_notice_recipient_falls_back_driver_then_starter_then_steering(test_db):
    from runtime.api.domain.machine_qa_session_seed import seed_qa_session
    from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver
    from runtime.api.fixtures.session_holdings import insert_steering_claim
    from yoke_core.domain.deployment_run_driver_notice import (
        resolve_run_driver_recipient,
    )

    _seed(test_db)
    seed_qa_session(test_db, DRIVER_SESSION, "run-starter")
    insert_steering_claim(test_db, "sess-steering")
    test_db.execute(
        "UPDATE deployment_runs SET created_by_session_id='run-starter' WHERE id=%s", (RUN,)
    )
    test_db.commit()

    def route():
        session, _actor, why = resolve_run_driver_recipient(test_db, run_id=RUN, project_id=1)
        return session, why

    assert route() == (DRIVER_SESSION, "driver")
    release_seeded_driver(test_db, RUN)
    assert route() == ("run-starter", "creator")
    test_db.execute(
        "UPDATE harness_sessions SET ended_at=now() WHERE session_id='run-starter'"
    )
    test_db.commit()
    assert route() == ("sess-steering", "steering")


def test_a_group_needing_human_acceptance_stays_open_until_accepted(test_db):
    from yoke_core.domain.decision_request_resolution import resolve_decision_request

    reviewer = 9899
    test_db.execute(
        "INSERT INTO actors(id,kind,created_at) VALUES "
        "(%s,'human','2026-09-14T00:00:00Z') ON CONFLICT(id) DO NOTHING",
        (reviewer,),
    )
    plan_id = _plan(test_db)
    stages = _stages(
        plan_id,
        verdict={
            "mode": "required_human",
            "reviewers": {"mode": "all", "roles": [], "actors": [reviewer]},
        },
    )
    stages[1].pop("cases")
    _seed_run(test_db, run_id=RUN, stages=stages, members=MEMBERS)
    for member in MEMBERS:
        _attach(test_db, member, plan_id)
    _form(test_db)

    def settle():
        (group,) = run_groups(test_db, [RUN], "item-qa")
        return settle_group(
            test_db, group_subject(test_db, RUN, "item-qa", group, require_active=False)
        )

    _complete_case(test_db, _begin(test_db))
    assert not settle()["accepted"]
    (group,) = run_groups(test_db, [RUN], "item-qa")
    assert group.open and group.covered_item_ids is None
    (request_id,) = test_db.execute(
        "SELECT id FROM decision_requests WHERE kind='qa_needs_review' AND status='pending'"
    ).fetchone()

    with mock.patch(
        "yoke_core.domain.deployment_run_driver_notice.push_run_scoped_notice",
        return_value="delivered",
    ):
        resolve_decision_request(
            test_db, int(request_id), actor_id=reviewer, action="approve",
            note="Reviewed the plan group for the release.",
        )
        settle()

    (group,) = run_groups(test_db, [RUN], "item-qa")
    assert group.closed and group.covered_item_ids == tuple(sorted(MEMBERS))
