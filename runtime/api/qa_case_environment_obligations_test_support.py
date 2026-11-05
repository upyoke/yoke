# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import importlib

import json

import pytest

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _complete_case,
    _environment,
    _seed_run,
    _stages,
)

from runtime.api.fixtures.backlog_inserts import insert_item

from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement

from runtime.api.fixtures.completed_delivery import pin_run_delivery

from yoke_core.domain.deployment_qa_plan_group_writes import (
    ensure_groups,
)

from yoke_core.domain.deployment_qa_plan_groups import run_groups

from yoke_core.domain.qa_catalog_reads import list_plans

from yoke_core.domain.qa_gates import GateTarget, check_done_gate

from yoke_core.domain.qa_plan_attachments import (
    materialize_for_item,
    set_project_default,
)

from yoke_core.domain.qa_plan_detail import get_plan

from yoke_core.domain.qa_plan_edit import _current_cases

from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

from yoke_core.domain.qa_plan_management import (
    QaPlanError,
    create_plan,
    replace_plan_cases,
)

from yoke_core.domain.qa_plan_summary import plan_summary

CASE = {
    "case_key": "environment-proof",
    "method_id": "command",
    "instructions": "Run the command against the case target.",
    "expected_outcome": "The target answers successfully.",
    "method_config": {"command": "true"},
    "target_envs": ["stage", "prod"],
    "stage_reason": "creates_or_destroys_data",
}

ITEM_ID = 28761

SLUG = "environment-obligations"


def _setup(conn, *, baselines=(), qa_phase="post_deploy"):
    _environment(conn)
    conn.execute(
        "INSERT INTO environments(site,project_id,name,url,settings,created_at) "
        "SELECT id,1,'prod','https://prod.example.test','{\"role\":{\"production\":true}}','2026-09-14T00:00:00Z' "
        "FROM sites WHERE project_id=1 ORDER BY id LIMIT 1 "
        "ON CONFLICT(project_id,name) DO NOTHING"
    )
    item = insert_item(
        conn,
        id=ITEM_ID,
        project_sequence=ITEM_ID,
        workflow_id="issue",
        status="release",
    )
    plan = create_plan(conn, project="yoke", slug=SLUG, target_environment="prod")
    case = {**CASE, "host_baselines": list(baselines)}
    if baselines:
        case.update(
            method_id="machine-state-check",
            method_config={"assertions": [{"argv": ["/usr/bin/true"]}]},
        )
    replace_plan_cases(conn, plan_id=plan["id"], cases=[case])
    set_project_default(
        conn,
        plan_id=plan["id"],
        workflow_id="issue",
        transition_id="release",
        qa_phase=qa_phase,
    )
    return item, plan, case
