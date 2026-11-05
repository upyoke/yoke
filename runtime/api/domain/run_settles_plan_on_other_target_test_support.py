# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

import pytest

from runtime.api.domain.release_member_target_enrollment_test_support import _pair

from runtime.api.domain.post_deploy_original_pass_needs_admission_test_support import (
    _record_evidence,
)

from runtime.api.domain.status_transition_preflight_test_support import (
    _isolate_status_effects,
)

from runtime.api.fixtures.backlog_inserts import insert_qa_requirement

from yoke_core.domain.deployment_qa_plan_credit import plan_credit_misses

from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)

from yoke_core.domain.deployment_run_other_target_members import owes_only_other_targets

from yoke_core.domain.deployment_runs_crud_mutate import cmd_update

from yoke_core.domain.no_obligation_member_close_out import satisfied_delivery_member

from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases

from yoke_core.domain.qa_plan_attachments import attach_plan_to_item

ITEM = 9788


def _plan_only_pair(conn, *, plan_environment="stage"):
    _pair(conn, item_id=ITEM)
    # Replace the fixture's ordinary intake with one standing plan. No own
    # requirement, snapshot case, or Production result may answer for it.
    conn.execute("DELETE FROM qa_requirements WHERE item_id=%s", (ITEM,))
    snapshot = json.dumps(
        {
            "schema": 1,
            "requirements": [],
            "selection": {"schema": 1, "requirement_ids": [], "plan_ids": []},
        }
    )
    conn.execute(
        "UPDATE deployment_run_items SET requirement_snapshot=%s,requirement_selection=NULL "
        "WHERE item_id=%s",
        (snapshot, ITEM),
    )
    plan = create_plan(
        conn,
        project="yoke",
        slug="other-target-plan",
        target_environment=plan_environment,
    )
    replace_plan_cases(
        conn,
        plan_id=int(plan["id"]),
        cases=[
            {
                "case_key": "only-case",
                "method_id": "command",
                "instructions": "Check behavior on the plan's declared target.",
                "expected_outcome": "The target passes its check.",
                "method_config": {"command": "true"},
                "target_envs": [plan_environment],
                "stage_reason": "creates_or_destroys_data",
            }
        ],
    )
    attach_plan_to_item(
        conn,
        plan_id=int(plan["id"]),
        item_id=ITEM,
        transition_id="release",
        qa_phase="post_deploy",
    )
    _record_evidence(conn, item_id=ITEM)
    conn.commit()
    return int(plan["id"])
