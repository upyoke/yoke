# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

from collections import Counter

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _plan,
    _seed_run,
    _stages,
)

from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement

from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups

from yoke_core.domain.deployment_qa_run_sharing import run_qa_sharing

from yoke_core.domain.deployment_run_member_presentation import removed_member_items

from yoke_core.domain.qa_activity_reads import read_activity

RUN = "run-plan-groups"

MEMBERS = (9901, 9902, 9903)


def _attach(conn, member, plan_id):
    conn.execute(
        "INSERT INTO qa_plan_item_attachments(item_id,plan_id,transition_id,qa_phase,attached_at) "
        "VALUES (%s,%s,'release','post_deploy','2026-10-14T00:00:00Z')",
        (member, plan_id),
    )
    conn.commit()


def _seed_three(conn, run_id=RUN, *, existing=False):
    """Three members attach one plan; two attach another shared plan."""
    plan_id = _plan(conn) if not existing else _plan_id(conn, "release-smoke")
    lone = _plan(conn, "lone-plan") if not existing else _plan_id(conn, "lone-plan")
    stages = _stages(plan_id)
    stages[1].pop("cases")
    if existing:
        _seed_run(
            conn, run_id=run_id, stages=stages, members=(), existing_members=MEMBERS
        )
        return plan_id, lone
    _seed_run(conn, run_id=run_id, stages=stages, members=MEMBERS)
    for member in MEMBERS:
        _attach(conn, member, plan_id)
    for member in MEMBERS[:2]:
        _attach(conn, member, lone)
    return plan_id, lone


def _plan_id(conn, slug):
    return int(
        conn.execute("SELECT id FROM qa_plans WHERE slug=%s", (slug,)).fetchone()[0]
    )


def _form_groups(conn, run_id=RUN):
    created = ensure_groups(conn, run_id, "item-qa")
    conn.commit()
    return created
