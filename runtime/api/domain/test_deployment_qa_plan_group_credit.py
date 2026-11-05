"""Plan-group credit read through the real target-aware completion-run choice.

Nothing here stubs ``latest_qa_member_run``: each member's completion flow is
pinned to the seeded run's flow, so the done gate picks the run it would pick
in production and reads the closed group's ``covered_item_ids`` from there.
"""

from runtime.api.domain.deployment_qa_plan_group_credit_test_support import (
    _misses as _misses,
    _pin as _pin,
    _stage_and_prod as _stage_and_prod,
)


from runtime.api.domain.deployment_qa_plan_group_execution_test_support import (
    OTHER,
    _begin,
    _fail_case,
    _settle,
)
from runtime.api.domain.deployment_qa_plan_groups_test_support import (
    MEMBERS,
    RUN,
    SLUG,
    _attach,
    _pass_group,
    _seed,
)
from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _complete_case,
    _plan,
)
from yoke_core.domain.deployment_item_completion_runs import latest_qa_member_run
from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups
from yoke_core.domain.deployment_qa_plan_groups import lineage_run_ids, run_groups
from yoke_core.domain.qa_item_obligation_queries import unsatisfied_blocking_many

SUCCESSOR = "run-plan-groups-successor"


def _successor(conn, members, *, flow=f"flow-{RUN}"):
    """A newer run of the same flow that superseded the seeded run."""
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,release_lineage,status,"
        "current_stage,created_at,supersedes_run_id) "
        "SELECT %s,project_id,%s,release_lineage,'executing','item-qa',"
        "'2026-09-15T00:00:00Z',id FROM deployment_runs WHERE id=%s",
        (SUCCESSOR, flow, RUN),
    )
    for member in members:
        conn.execute(
            "INSERT INTO deployment_run_items(run_id,item_id,added_at) VALUES (%s,%s,%s)",
            (SUCCESSOR, member, "2026-09-15T00:00:00Z"),
        )
    conn.commit()


def test_the_completion_run_s_closed_group_credits_its_covered_members(test_db):
    _seed(test_db, attached=MEMBERS[:2])
    _pin(test_db, f"flow-{RUN}")
    assert latest_qa_member_run(test_db, item_id=MEMBERS[0], target_env="")["id"] == RUN
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    assert _misses(test_db, MEMBERS[0]) == [(SLUG, RUN)]

    _pass_group(test_db)

    assert _misses(test_db, MEMBERS[0]) == []
    assert _misses(test_db, MEMBERS[1]) == []
    blocking = unsatisfied_blocking_many(
        test_db, item_ids=MEMBERS[:2], target_status="done"
    )
    assert all(
        not any(r["qa_kind"] == "plan_group" for r in b.rows) for b in blocking.values()
    )


def test_a_superseding_run_credits_through_its_lineage(test_db):
    plan_id = _seed(test_db, attached=MEMBERS[:2])
    _pin(test_db, f"flow-{RUN}")
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    _pass_group(test_db)
    _attach(test_db, MEMBERS[2], plan_id)
    _successor(test_db, MEMBERS)

    assert (
        latest_qa_member_run(test_db, item_id=MEMBERS[0], target_env="")["id"]
        == SUCCESSOR
    )
    assert lineage_run_ids(test_db, SUCCESSOR) == [SUCCESSOR, RUN]
    assert run_groups(test_db, [SUCCESSOR]) == []
    assert _misses(test_db, MEMBERS[0]) == []
    assert _misses(test_db, MEMBERS[1]) == []
    # The late attacher is absent from the closed group's list: still owed.
    assert _misses(test_db, MEMBERS[2]) == [(SLUG, SUCCESSOR)]


def test_a_member_removed_after_the_pass_keeps_the_rows_but_loses_credit(test_db):
    _seed(test_db, attached=MEMBERS[:2])
    _pin(test_db, f"flow-{RUN}")
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    _pass_group(test_db)
    test_db.execute(
        "DELETE FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
        (RUN, MEMBERS[1]),
    )
    test_db.commit()

    (group,) = run_groups(test_db, [RUN], "item-qa")
    assert sorted(group.covered_item_ids) == sorted(MEMBERS[:2])
    assert _misses(test_db, MEMBERS[0]) == []
    assert [slug for slug, _ in _misses(test_db, MEMBERS[1])] == [SLUG]


def test_a_supplemental_stage_run_carrying_the_landing_credits(
    test_db, tmp_path, monkeypatch
):
    from yoke_core.domain.deployment_run_member_targeting import supplemental_qa_run

    _stage_and_prod(test_db, tmp_path, monkeypatch)
    assert supplemental_qa_run(test_db, run_id=RUN, item_id=MEMBERS[0])
    assert (
        latest_qa_member_run(test_db, item_id=MEMBERS[0], target_env="stage")["id"]
        == RUN
    )
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    assert _misses(test_db, MEMBERS[0]) == [(SLUG, RUN)]

    _pass_group(test_db)

    for member in MEMBERS:
        assert _misses(test_db, member) == []


def test_a_verification_pass_of_the_plan_never_answers_post_deploy(test_db):
    plan_id = _seed(test_db, attached=MEMBERS[:2])
    _pin(test_db, f"flow-{RUN}")
    test_db.execute(
        "INSERT INTO qa_plan_item_attachments(item_id,plan_id,transition_id,qa_phase,"
        "attached_at) VALUES (%s,%s,'implemented','verification','2026-10-28T00:00:00Z')",
        (MEMBERS[0], plan_id),
    )
    requirement = test_db.execute(
        "INSERT INTO qa_requirements(item_id,plan_id,plan_case_key,qa_phase,qa_kind,"
        "blocking_mode,created_at) VALUES (%s,%s,'command-smoke','verification',"
        "'plan_case','blocking','2026-10-28T00:00:00Z') RETURNING id",
        (MEMBERS[0], plan_id),
    ).fetchone()[0]
    test_db.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,started_at,"
        "completed_at,created_at) VALUES (%s,'worktree_run','plan_case','pass',"
        "'2026-10-28T00:00:00Z','2026-10-28T00:00:01Z','2026-10-28T00:00:01Z')",
        (requirement,),
    )
    test_db.commit()

    assert _misses(test_db, MEMBERS[0]) == [(SLUG, RUN)]
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    (group,) = run_groups(test_db, [RUN], "item-qa")
    assert group.open and group.plan_id == plan_id


def test_an_item_with_one_passed_and_one_failed_plan_is_not_done(test_db):
    _seed(test_db)
    other = _plan(test_db, OTHER)
    for member in MEMBERS[1:]:
        _attach(test_db, member, other)
    _pin(test_db, f"flow-{RUN}")
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    groups = {g.plan_id: g for g in run_groups(test_db, [RUN], "item-qa")}

    _complete_case(test_db, _begin(test_db))
    _fail_case(test_db, _begin(test_db, OTHER, session="other-plan-qa"))
    for group in groups.values():
        _settle(test_db, group)

    assert _misses(test_db, MEMBERS[-1]) == [(OTHER, RUN)]
    assert _misses(test_db, MEMBERS[0]) == []
    blocking = unsatisfied_blocking_many(
        test_db, item_ids=[MEMBERS[-1]], target_status="done"
    )[MEMBERS[-1]]
    assert blocking.count >= 1 and blocking.includes_post_deploy
    assert [r["plan_slug"] for r in blocking.rows if r["qa_kind"] == "plan_group"] == [
        OTHER
    ]
