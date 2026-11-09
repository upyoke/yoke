"""A release runs each attached post-deploy plan once, as one plan group."""

from runtime.api.domain.deployment_qa_plan_groups_test_support import (
    MEMBERS as MEMBERS,
    RUN as RUN,
    SLUG as SLUG,
    _attach as _attach,
    _begin as _begin,
    _pass_group as _pass_group,
    _seed as _seed,
)


import pytest

from yoke_core.domain.deployment_qa_plan_group_writes import (
    ensure_groups,
)
from yoke_core.domain.deployment_qa_plan_groups import (
    retract_unattached_groups,
    run_groups,
)


def _plan_rows(conn):
    return conn.execute(
        "SELECT item_id, deployment_member_item_id FROM qa_requirements "
        "WHERE plan_id IS NOT NULL ORDER BY id"
    ).fetchall()


def test_attachment_writes_no_item_copies_and_dispatch_forms_one_group(test_db):
    plan_id = _seed(test_db)
    assert _plan_rows(test_db) == []

    created = ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    assert ensure_groups(test_db, RUN, "item-qa") == []

    groups = run_groups(test_db, [RUN], "item-qa")
    assert [(g.plan_id, g.group_id) for g in groups] == [(plan_id, f"{RUN}:1")]
    assert sorted(groups[0].requirement_ids) == sorted(created)
    assert all(row[0] is None and row[1] is None for row in _plan_rows(test_db))


def test_one_pass_closes_the_group_and_covers_every_attaching_member(test_db):
    _seed(test_db)
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()

    execution = _pass_group(test_db)

    assert execution["deployment_member_item_id"] is None
    group = run_groups(test_db, [RUN], "item-qa")[0]
    assert group.closed
    assert sorted(group.covered_item_ids) == sorted(MEMBERS)
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM qa_plan_executions WHERE deployment_run_id=%s", (RUN,)
        ).fetchone()[0]
        == 1
    )


def test_a_later_attachment_is_owed_a_new_group(test_db):
    plan_id = _seed(test_db, attached=MEMBERS[:2])
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    _pass_group(test_db)

    _attach(test_db, MEMBERS[2], plan_id)
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()

    first, second = run_groups(test_db, [RUN], "item-qa")
    assert sorted(first.covered_item_ids) == sorted(MEMBERS[:2])
    assert second.group_id == f"{RUN}:2" and second.open


def test_an_unattached_member_cannot_run_the_group(test_db):
    _seed(test_db, attached=MEMBERS[:2])
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    with pytest.raises(ValueError, match="plan_group_member_unattached"):
        _begin(test_db, MEMBERS[2])


def test_detaching_retracts_the_open_group_but_never_a_passed_one(test_db):
    plan_id = _seed(test_db)
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    _pass_group(test_db)
    test_db.execute("DELETE FROM qa_plan_item_attachments WHERE plan_id=%s", (plan_id,))
    test_db.commit()

    assert (
        retract_unattached_groups(test_db, RUN, reason="detached", source="test") == []
    )
    assert not run_groups(test_db, [RUN], "item-qa")[0].retracted


def test_the_done_gate_credits_covered_members_from_the_closed_group(
    test_db, monkeypatch
):
    from yoke_core.domain import deployment_item_completion_runs as completion
    from yoke_core.domain.deployment_qa_plan_credit import plan_credit_misses

    # This run is each member's completion run; the credit read is under test.
    monkeypatch.setattr(
        completion, "latest_qa_member_run", lambda conn, **_: {"id": RUN}
    )

    _seed(test_db, attached=MEMBERS[:2])
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    owed = plan_credit_misses(test_db, MEMBERS[0])
    assert [(m["plan_slug"], m["deployment_run_id"]) for m in owed] == [(SLUG, RUN)]
    assert f"--plan {SLUG}" in owed[0]["recovery"]

    _pass_group(test_db)

    assert plan_credit_misses(test_db, MEMBERS[0]) == []
    assert plan_credit_misses(test_db, MEMBERS[1]) == []
    assert plan_credit_misses(test_db, MEMBERS[2]) == []  # attaches nothing


def test_the_done_refusal_names_the_plan_group_command_only(test_db):
    from yoke_core.domain.deployment_qa_plan_credit import _miss
    from yoke_core.domain.deployment_qa_source_obligation import POST_DEPLOY_RECOVERY
    from yoke_core.domain.qa_done_gate_refusal import done_gate_refusal_errors

    miss = _miss(MEMBERS[0], 7, SLUG, {"id": RUN}, "item-qa", "stage", conn=test_db)
    text = "\n".join(done_gate_refusal_errors(test_db, [miss], name="YOK-1"))

    assert f"Post-deploy plan {SLUG}: Awaiting stage plan {SLUG} QA credit" in text
    assert f"on deployment run {RUN}" in text
    assert "on its completion run" not in text
    assert (
        f"yoke qa plan run --deployment-run-id {RUN} --stage item-qa --plan {SLUG}"
        in text
    )
    assert POST_DEPLOY_RECOVERY not in text


def test_a_finished_group_walk_wakes_the_run_recipient_not_a_member(
    test_db, monkeypatch
):
    from yoke_core.domain import deployment_run_driver_notice as notice
    from yoke_core.domain.qa_plan_agent_review_wake import notify_scoped_agent_review

    _seed(test_db)
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    execution = _begin(test_db)
    sent = []
    monkeypatch.setattr(
        notice,
        "push_run_scoped_notice",
        lambda conn, **kwargs: sent.append(kwargs) or "delivered",
    )

    result = notify_scoped_agent_review(test_db, {**execution, "state": "completed"})

    assert result == "delivered"
    assert [call["run_id"] for call in sent] == [RUN]
    body = sent[0]["body_for_route"](None)
    assert "plan group" in body and execution["id"] in body


def test_a_member_stands_on_its_open_plan_group_until_the_group_passes(test_db):
    from yoke_core.domain.deployment_qa_run_acceptance import (
        current_item_qa,
        item_qa_acceptance_blockers,
    )

    _seed(test_db, attached=MEMBERS[:2])
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()

    def standing(member):
        return current_item_qa(
            test_db, run_id=RUN, item_id=member, current_stage="item-qa"
        )

    held = standing(MEMBERS[0])
    assert not held.accepted
    assert any(f"plan group {RUN}:1 ({SLUG})" in b for b in held.blockers)
    assert item_qa_acceptance_blockers(test_db, run_id=RUN, item_id=MEMBERS[0])

    _pass_group(test_db)

    assert standing(MEMBERS[0]).accepted
    assert item_qa_acceptance_blockers(test_db, run_id=RUN, item_id=MEMBERS[0]) == []


def test_plan_groups_never_answer_a_member_s_own_unrun_cases(test_db):
    from yoke_core.domain.post_deploy_verification_answer import (
        PLAN_GROUPS,
        member_post_deploy_answer,
    )

    _seed(test_db, attached=MEMBERS[:2])
    subject = {"id": RUN, "member_item_id": MEMBERS[0]}
    own_case = {"plan_id": None, "qa_phase": "post_deploy", "id": 1}

    assert member_post_deploy_answer(test_db, subject).verdict == PLAN_GROUPS
    assert (
        member_post_deploy_answer(
            test_db, {**subject, "member_snapshot": {"requirements": [own_case]}}
        ).verdict
        != PLAN_GROUPS
    )


def test_an_unattached_group_whose_rows_passed_closes_covering_nobody(test_db):
    plan_id = _seed(test_db)
    created = ensure_groups(test_db, RUN, "item-qa")
    for requirement_id in created:  # passed, but the stage was never accepted
        test_db.execute(
            "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
            "started_at,completed_at,created_at) VALUES (%s,'worktree_run','plan_case',"
            "'pass','2026-10-28T00:00:00Z','2026-10-28T00:00:01Z','2026-10-28T00:00:01Z')",
            (requirement_id,),
        )
    test_db.execute("DELETE FROM qa_plan_item_attachments WHERE plan_id=%s", (plan_id,))
    test_db.commit()

    assert (
        retract_unattached_groups(test_db, RUN, reason="detached", source="test") == []
    )
    (group,) = run_groups(test_db, [RUN], "item-qa")
    assert group.closed and group.covered_item_ids == () and not group.retracted
    _attach(test_db, MEMBERS[0], plan_id)
    ensure_groups(test_db, RUN, "item-qa")
    assert run_groups(test_db, [RUN], "item-qa")[-1].group_id == f"{RUN}:2"
