"""Plan-group credit read through the real target-aware completion-run choice.

Nothing here stubs ``latest_qa_member_run``: each member's completion flow is
pinned to the seeded run's flow, so the done gate picks the run it would pick
in production and reads the closed group's ``covered_item_ids`` from there.
"""

from runtime.api.domain.test_deployment_qa_plan_group_execution import (
    OTHER,
    _begin,
    _fail_case,
    _settle,
)
from runtime.api.domain.test_deployment_qa_plan_groups import (
    MEMBERS,
    RUN,
    SLUG,
    _attach,
    _pass_group,
    _seed,
)
from runtime.api.domain.test_deployment_qa_stage_execution import (
    _complete_case,
    _plan,
    _seed_run,
    _stages,
)
from yoke_core.domain.deployment_item_completion_runs import latest_qa_member_run
from yoke_core.domain.deployment_qa_plan_credit import plan_credit_misses
from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups
from yoke_core.domain.deployment_qa_plan_groups import lineage_run_ids, run_groups
from yoke_core.domain.qa_item_obligation_queries import unsatisfied_blocking_many

SUCCESSOR = "run-plan-groups-successor"


def _pin(conn, flow, members=MEMBERS):
    conn.execute(
        "UPDATE items SET deployment_flow=%s WHERE id=ANY(%s)", (flow, list(members))
    )
    conn.commit()


def _misses(conn, member):
    return [(m["plan_slug"], m["deployment_run_id"]) for m in plan_credit_misses(conn, member)]


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
    assert all(not any(r["qa_kind"] == "plan_group" for r in b.rows) for b in blocking.values())


def test_a_superseding_run_credits_through_its_lineage(test_db):
    plan_id = _seed(test_db, attached=MEMBERS[:2])
    _pin(test_db, f"flow-{RUN}")
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    _pass_group(test_db)
    _attach(test_db, MEMBERS[2], plan_id)
    _successor(test_db, MEMBERS)

    assert latest_qa_member_run(test_db, item_id=MEMBERS[0], target_env="")["id"] == SUCCESSOR
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
        "DELETE FROM deployment_run_items WHERE run_id=%s AND item_id=%s", (RUN, MEMBERS[1])
    )
    test_db.commit()

    (group,) = run_groups(test_db, [RUN], "item-qa")
    assert sorted(group.covered_item_ids) == sorted(MEMBERS[:2])
    assert _misses(test_db, MEMBERS[0]) == []
    assert [slug for slug, _ in _misses(test_db, MEMBERS[1])] == [SLUG]


def _stage_and_prod(conn, tmp_path, monkeypatch):
    """A stage QA run beside a production final run containing real landings.

    The members' completion flow targets production; the seeded stage run is
    supplemental and carries every recorded landing.
    """
    from yoke_core.domain.deployment_flow_versioning import cmd_create

    from runtime.api.domain.test_deployment_qa_stage_execution import _environment

    _environment(conn)
    plan_id = _plan(conn, target_envs=["stage"])
    stages = _stages(plan_id)
    stages[1].pop("cases")
    _seed_run(conn, run_id=RUN, stages=stages, members=MEMBERS)
    for member in MEMBERS:
        _attach(conn, member, plan_id)
    conn.execute(
        "INSERT INTO environments(site,project_id,name,url,settings,created_at) "
        "SELECT site,1,'prod','https://prod.example.test',"
        '\'{"role":{"production":true}}\',created_at FROM environments '
        "WHERE project_id=1 AND name='stage'"
    )
    prod_stages = [dict(s) for s in stages]
    prod_stages[1] = {**prod_stages[1], "target": {**prod_stages[1]["target"], "environment": "prod"}}
    import json

    cmd_create(conn, "flow-prod", "yoke", "flow-prod", "", json.dumps(prod_stages), status="disabled")
    for flow, env in ((f"flow-{RUN}", "stage"), ("flow-prod", "prod")):
        conn.execute(
            "UPDATE deployment_flows SET target_tier='persistent',target_environment_id=(SELECT id FROM "
            "environments WHERE project_id=1 AND name=%s) WHERE id=%s",
            (env, flow),
        )
    conn.execute(
        "UPDATE deployment_runs SET target_tier='persistent',target_environment_id=(SELECT id FROM environments "
        "WHERE project_id=1 AND name='stage') WHERE id=%s",
        (RUN,),
    )
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,release_lineage,status,"
        "current_stage,created_at,target_tier,target_environment_id) SELECT 'run-prod',1,"
        "'flow-prod',release_lineage,'executing','deploy','2026-09-15T00:00:00Z','persistent',"
        "(SELECT id FROM environments WHERE project_id=1 AND name='prod') "
        "FROM deployment_runs WHERE id=%s",
        (RUN,),
    )
    for member in MEMBERS:
        conn.execute(
            "INSERT INTO deployment_run_items(run_id,item_id,added_at) VALUES "
            "('run-prod',%s,'2026-09-15T00:00:00Z')",
            (member,),
        )
    conn.commit()
    _pin(conn, "flow-prod")
    from runtime.api.fixtures.carried_release_candidate import (
        release_repository, serve_repository, record_landing_receipt,
    )
    from runtime.api.fixtures.supplemental_credit import pin

    repo, _, landing = release_repository(tmp_path, "shared-plan-release")
    serve_repository(monkeypatch, repo)
    for member in MEMBERS:
        record_landing_receipt(conn, member, branch="feature", tip=landing)
    pin(conn, RUN, landing)
    pin(conn, "run-prod", landing)
    return plan_id


def test_a_supplemental_stage_run_carrying_the_landing_credits(test_db, tmp_path, monkeypatch):
    from yoke_core.domain.deployment_run_member_targeting import supplemental_qa_run

    _stage_and_prod(test_db, tmp_path, monkeypatch)
    assert supplemental_qa_run(test_db, run_id=RUN, item_id=MEMBERS[0])
    assert latest_qa_member_run(test_db, item_id=MEMBERS[0], target_env="stage")["id"] == RUN
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    assert _misses(test_db, MEMBERS[0]) == [(SLUG, RUN)]

    _pass_group(test_db)

    for member in MEMBERS:
        assert _misses(test_db, member) == []


def test_a_verification_pass_of_the_plan_never_answers_post_deploy(test_db):
    plan_id = _seed(test_db, attached=MEMBERS[:1])
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
    _attach(test_db, MEMBERS[-1], other)
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
    assert [r["plan_slug"] for r in blocking.rows if r["qa_kind"] == "plan_group"] == [OTHER]
