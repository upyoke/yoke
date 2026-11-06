# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

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
    _seed_run,
    _stages,
)

from yoke_core.domain.deployment_item_completion_runs import latest_qa_member_run

from yoke_core.domain.deployment_qa_plan_credit import plan_credit_misses

from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups

from yoke_core.domain.deployment_qa_plan_groups import lineage_run_ids, run_groups

from yoke_core.domain.qa_item_obligation_queries import unsatisfied_blocking_many


def _pin(conn, flow, members=MEMBERS):
    conn.execute(
        "UPDATE items SET deployment_flow=%s WHERE id=ANY(%s)", (flow, list(members))
    )
    conn.commit()


def _misses(conn, member):
    return [
        (m["plan_slug"], m["deployment_run_id"])
        for m in plan_credit_misses(conn, member)
    ]


def _stage_and_prod(conn, tmp_path, monkeypatch):
    """A stage QA run beside a production final run containing real landings.

    The members' completion flow targets production; the seeded stage run is
    supplemental and carries every recorded landing.
    """
    from yoke_core.domain.deployment_flow_versioning import cmd_create

    from runtime.api.domain.deployment_qa_stage_execution_test_support import (
        _environment,
    )

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
    prod_stages[1] = {
        **prod_stages[1],
        "target": {**prod_stages[1]["target"], "environment": "prod"},
    }
    import json

    cmd_create(
        conn,
        "flow-prod",
        "yoke",
        "flow-prod",
        "",
        json.dumps(prod_stages),
        status="disabled",
    )
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
        release_repository,
        serve_repository,
        record_landing_receipt,
    )
    from runtime.api.fixtures.supplemental_credit import pin

    repo, _, landing = release_repository(tmp_path, "shared-plan-release")
    serve_repository(monkeypatch, repo)
    for member in MEMBERS:
        record_landing_receipt(conn, member, branch="feature", tip=landing)
    pin(conn, RUN, landing)
    pin(conn, "run-prod", landing)
    return plan_id
