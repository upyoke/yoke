# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

from yoke_contracts.timestamps import parse_instant

import pytest

from runtime.api.domain.coordination_claim_test_support import seed_project

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _complete_case,
    _plan,
    _seed_run,
    _stages,
)

from runtime.api.domain.no_obligation_member_close_out_test_support import (
    _landing_evidence,
)

from runtime.api.domain.status_transition_preflight_test_support import (
    _isolate_status_effects,
)

from runtime.api.fixtures.backlog_inserts import insert_item, insert_qa_requirement

from yoke_core.domain.deployment_delivery_close_out_notice import (
    notify_delivery_cleared,
)

from yoke_core.domain.deployment_qa_stage_acceptance import stage_acceptance

from yoke_core.domain.deployment_qa_stage_contract import deployment_qa_stage_subject

from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)

from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)

from yoke_core.domain.deployment_qa_stage_gate import (
    ACCEPTANCE_QA_KIND,
    deployment_qa_stage_status,
)

from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)

from yoke_core.domain.deployment_qa_stage_outstanding import qa_stage_outstanding

from yoke_core.domain.deployment_qa_stage_prerequisites import (
    prior_stage_refusals,
    require_prior_stage_acceptance,
)

from yoke_core.domain.deployment_requirement_snapshots import (
    requirement_selection,
    snapshot_member_requirements,
)

from yoke_core.domain.post_deploy_verification_answer import answer_for_item

from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases

from yoke_core.domain.steering_fleet_report_run_progress import run_progress

RUN = "run-carried-item-qa"

MEMBER = 9951

OTHER = 995

OWN_FLOW = "carried-completion"


def _ready(conn, *, own_qa=False, same_project=False, cases=False, follow_stage=False):
    seed_project(conn, OTHER, "carried")
    site = conn.execute(
        "INSERT INTO sites(project_id,name,created_at) VALUES (%s,'app','2026-10-01T00:00:00Z') RETURNING id",
        (OTHER,),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO environments(site,project_id,name,url,created_at) VALUES (%s,%s,'prod','https://carried.example.test','2026-10-01T00:00:00Z')",
        (site, OTHER),
    )
    plan = _plan(conn)
    stages = _stages(plan)
    if not cases:
        stages[1].pop("cases")
    if follow_stage:
        stages.append({**stages[1], "name": "later-item-qa"})
    own_stages = [stages[1]] if own_qa else []
    conn.execute(
        "INSERT INTO deployment_flows(id,project_id,name,stages,created_at) "
        "VALUES (%s,%s,%s,%s,'2026-10-01T00:00:00Z')",
        (OWN_FLOW, OTHER, OWN_FLOW, json.dumps(own_stages)),
    )
    insert_item(
        conn,
        id=MEMBER,
        project_id=1 if same_project else OTHER,
        workflow_id="dash",
        status="release",
        deployment_flow=OWN_FLOW,
    )
    _seed_run(conn, run_id=RUN, stages=stages, members=(), existing_members=(MEMBER,))
    conn.execute(
        "INSERT INTO environments(site,project_id,name,url,created_at) "
        "VALUES (%s,%s,'stage','https://carried.example.test','2026-10-01T00:00:00Z')",
        (site, OTHER),
    )
    # This command-only producer does not observe a browser endpoint.
    conn.execute(
        "UPDATE deployment_stage_receipts SET observed_url=NULL WHERE run_id=%s",
        (RUN,),
    )
    conn.execute(
        "UPDATE deployment_runs SET bound_sources=%s WHERE id=%s",
        (
            json.dumps(
                {
                    "schema": 1,
                    "projects": [{"project_id": OTHER, "commit_sha": "b" * 40}],
                }
            ),
            RUN,
        ),
    )
    conn.commit()
    return stages[1]
